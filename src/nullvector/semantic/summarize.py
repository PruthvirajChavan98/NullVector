"""Bottom-up summarization over committed hierarchy nodes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Any, cast

from nullvector.domain.tree import (
    HierarchyNode,
    NodeCard,
    NodeSummary,
    NodeSummaryMethod,
    SemanticUsage,
)
from nullvector.llm.prompts import SummarizationPromptResponse, build_summarization_messages
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest, GatewayUsage
from nullvector.observability.logging import log_event
from nullvector.semantic._text_spans import (
    _TextPage,
    bounded_fragments,
    text_for_node,
    text_fragments_for_node,
)
from nullvector.storage._serialization import write_json_file
from nullvector.tree.page_data import PageData as PageArtifacts

LEAF_PASSTHROUGH_WORD_THRESHOLD = 150


def estimate_token_count(text: str) -> int:
    """Rough word-count-based token estimator."""

    return len(text.split())


def _usage_snapshot(usage: GatewayUsage | None) -> SemanticUsage | None:
    if usage is None:
        return None
    return SemanticUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def _stable_node_order(node: HierarchyNode) -> tuple[int, int, str]:
    return (
        node.page_span.start_page,
        node.level,
        node.node_id,
    )


def _pages_for_node(
    node: HierarchyNode,
    pages_by_index: dict[int, PageArtifacts],
) -> tuple[PageArtifacts, ...]:
    return tuple(
        pages_by_index[page_index]
        for page_index in range(node.page_span.start_page, node.page_span.end_page + 1)
        if page_index in pages_by_index
    )


def _node_raw_text(node: HierarchyNode, pages_by_index: dict[int, PageArtifacts]) -> str:
    return text_for_node(node, cast(Mapping[int, _TextPage], pages_by_index))


def _bounded_leaf_excerpts(
    node: HierarchyNode, pages_by_index: dict[int, PageArtifacts]
) -> tuple[str, ...]:
    return bounded_fragments(
        text_fragments_for_node(node, cast(Mapping[int, _TextPage], pages_by_index)),
        max_chars=1600,
    )


def _parent_prefix_text(
    node: HierarchyNode,
    children: tuple[HierarchyNode, ...],
    pages_by_index: dict[int, PageArtifacts],
) -> str:
    if not children:
        return _node_raw_text(node, pages_by_index)

    first_child = sorted(children, key=_stable_node_order)[0]
    parts: list[str] = []
    for page in _pages_for_node(node, pages_by_index):
        if page.page_index < node.page_span.start_page:
            continue
        if page.page_index > first_child.page_span.start_page:
            break
        parts.append(page.text.strip())
    return "\n".join(part for part in parts if part).strip()


@dataclass(frozen=True)
class _PendingSummaryRequest:
    index: int
    node: HierarchyNode
    summary_method: NodeSummaryMethod
    token_count: int
    estimated_token_count: int
    exact_token_count: int | None
    request: GatewayRequest[SummarizationPromptResponse]


class NodeSummarizer:
    """Bottom-up committed-node summarizer over normalized synthesis text."""

    def __init__(
        self,
        gateway: StructuredLLMGateway,
        max_workers: int = 4,
        logger: Logger | None = None,
    ) -> None:
        self._gateway = gateway
        self._max_workers = max_workers
        self._logger = logger
        self._artifact_path: str | None = None

    @property
    def artifact_path(self) -> str | None:
        return self._artifact_path

    def summarize(
        self,
        *,
        nodes: tuple[HierarchyNode, ...],
        pages: tuple[PageArtifacts, ...],
        artifact_root: str | None = None,
        artifact_writer: Callable[[str, Any], str] | None = None,
    ) -> tuple[tuple[HierarchyNode, ...], tuple[NodeCard, ...], tuple[NodeSummary, ...]]:
        pages_by_index = {page.page_index: page for page in pages}
        children_by_parent: dict[str, tuple[HierarchyNode, ...]] = {}
        for node in nodes:
            if node.parent_id is None:
                continue
            siblings = list(children_by_parent.get(node.parent_id, ()))
            siblings.append(node)
            children_by_parent[node.parent_id] = tuple(sorted(siblings, key=_stable_node_order))

        summaries_by_id: dict[str, NodeSummary] = {}
        ordered_nodes = sorted(nodes, key=_stable_node_order)
        levels = sorted({node.level for node in ordered_nodes}, reverse=True)

        for level in levels:
            level_nodes = [node for node in ordered_nodes if node.level == level]
            level_summaries: list[NodeSummary | None] = [None] * len(level_nodes)
            pending_requests: list[_PendingSummaryRequest] = []
            for index, node in enumerate(level_nodes):
                summary, pending_request = self._prepare_node_summary(
                    index=index,
                    node=node,
                    pages_by_index=pages_by_index,
                    children=children_by_parent.get(node.node_id, ()),
                    summaries_by_id=summaries_by_id,
                )
                if summary is not None:
                    level_summaries[index] = summary
                if pending_request is not None:
                    pending_requests.append(pending_request)

            if pending_requests:
                responses = self._gateway.invoke_many(
                    tuple(item.request for item in pending_requests),
                    max_workers=self._max_workers,
                )
                for pending_request, response in zip(pending_requests, responses, strict=True):
                    summary = NodeSummary(
                        node_id=pending_request.node.node_id,
                        summary=response.output.summary,
                        keywords=response.output.keywords,
                        summary_method=pending_request.summary_method,
                        token_count=pending_request.token_count,
                        estimated_token_count=pending_request.estimated_token_count,
                        exact_token_count=pending_request.exact_token_count,
                        tokenizer_identity="word_count",
                        gateway_provider_name=response.provider_name,
                        gateway_assurance_mode=response.assurance_mode.value,
                        gateway_audit_path=response.audit_path,
                        gateway_usage=_usage_snapshot(response.usage),
                    )
                    self._publish_summary_event(pending_request.node, summary)
                    level_summaries[pending_request.index] = summary

            for summary in level_summaries:
                if summary is None:
                    msg = "level summary was not populated for node (internal invariant)"
                    raise RuntimeError(msg)
                summaries_by_id[summary.node_id] = summary

        ordered_summaries = tuple(summaries_by_id[node.node_id] for node in ordered_nodes)
        node_cards = tuple(
            NodeCard(
                node_id=node.node_id,
                document_id=node.document_id,
                path=node.path,
                level=node.level,
                title=node.title,
                page_span=node.page_span,
                owned_spans=node.owned_spans,
                summary=summaries_by_id[node.node_id].summary,
                keywords=summaries_by_id[node.node_id].keywords,
                summary_method=summaries_by_id[node.node_id].summary_method,
                summary_token_count=summaries_by_id[node.node_id].token_count,
                source_anchors=node.source_anchors,
            )
            for node in ordered_nodes
        )
        if artifact_writer is not None:
            self._artifact_path = artifact_writer(
                "summaries/node-summaries.json",
                ordered_summaries,
            )
        elif artifact_root is not None:
            self._artifact_path = write_json_file(
                Path(artifact_root) / "summaries" / "node-summaries.json",
                ordered_summaries,
            )
        return tuple(ordered_nodes), node_cards, ordered_summaries

    def _prepare_node_summary(
        self,
        *,
        index: int,
        node: HierarchyNode,
        pages_by_index: dict[int, PageArtifacts],
        children: tuple[HierarchyNode, ...],
        summaries_by_id: dict[str, NodeSummary],
    ) -> tuple[NodeSummary | None, _PendingSummaryRequest | None]:
        if not children:
            raw_text = _node_raw_text(node, pages_by_index)
            token_count, estimated_token_count, exact_token_count = self._token_counts(raw_text)
            if token_count < LEAF_PASSTHROUGH_WORD_THRESHOLD:
                summary = NodeSummary(
                    node_id=node.node_id,
                    summary=raw_text or node.title,
                    summary_method=NodeSummaryMethod.PASSTHROUGH,
                    token_count=token_count,
                    estimated_token_count=estimated_token_count,
                    exact_token_count=exact_token_count,
                    tokenizer_identity="word_count",
                )
                self._publish_summary_event(node, summary)
                return summary, None
            return None, _PendingSummaryRequest(
                index=index,
                node=node,
                summary_method=NodeSummaryMethod.LLM_LEAF,
                token_count=token_count,
                estimated_token_count=estimated_token_count,
                exact_token_count=exact_token_count,
                request=GatewayRequest[SummarizationPromptResponse](
                    operation_name="summarize_leaf_node",
                    messages=build_summarization_messages(
                        node_title=node.title,
                        excerpts=_bounded_leaf_excerpts(node, pages_by_index),
                    ),
                    response_model=SummarizationPromptResponse,
                ),
            )

        child_pairs = tuple(
            (child.title, summaries_by_id[child.node_id].summary)
            for child in sorted(children, key=_stable_node_order)
        )
        prefix_text = _parent_prefix_text(node, children, pages_by_index)
        semantic_text = (
            prefix_text + "\n" + "\n".join(f"{title}: {summary}" for title, summary in child_pairs)
        )
        token_count, estimated_token_count, exact_token_count = self._token_counts(semantic_text)
        return None, _PendingSummaryRequest(
            index=index,
            node=node,
            summary_method=NodeSummaryMethod.LLM_PARENT,
            token_count=token_count,
            estimated_token_count=estimated_token_count,
            exact_token_count=exact_token_count,
            request=GatewayRequest[SummarizationPromptResponse](
                operation_name="summarize_parent_node",
                messages=build_summarization_messages(
                    node_title=node.title,
                    parent_prefix_text=prefix_text,
                    child_summaries=child_pairs,
                ),
                response_model=SummarizationPromptResponse,
            ),
        )

    def _token_counts(self, text: str) -> tuple[int, int, int | None]:
        word_count = len(text.split())
        return word_count, word_count, None

    def _publish_summary_event(self, node: HierarchyNode, summary: NodeSummary) -> None:
        log_event(
            self._logger,
            "NodeSummarized",
            document_id=node.document_id,
            node_id=node.node_id,
            summary_method=summary.summary_method.value,
        )


__all__ = [
    "LEAF_PASSTHROUGH_WORD_THRESHOLD",
    "NodeSummarizer",
    "estimate_token_count",
]
