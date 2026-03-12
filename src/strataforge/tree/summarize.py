"""Bottom-up summarization for committed hierarchy nodes."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from strataforge.domain.models import (
    HierarchyNode,
    NodeCard,
    NodeSummary,
    NodeSummaryMethod,
)
from strataforge.llm.prompts import SummarizationPromptResponse, build_summarization_messages
from strataforge.llm.protocols import StructuredLLMGateway
from strataforge.llm.types import GatewayRequest
from strataforge.tree.headings import PageArtifacts

LEAF_PASSTHROUGH_TOKEN_THRESHOLD = 200


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    return str(path)


def estimate_token_count(text: str) -> int:
    """Deterministic token estimator for bounded summarization decisions."""

    return max(1, int(len(text.split()) * 1.3))


def _stable_node_order(node: HierarchyNode) -> tuple[int, int, int, str]:
    return (
        node.page_span.start_page,
        node.heading_anchor.start_offset,
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
    return "\n".join(page.text for page in _pages_for_node(node, pages_by_index)).strip()


def _bounded_leaf_excerpts(
    node: HierarchyNode, pages_by_index: dict[int, PageArtifacts]
) -> tuple[str, ...]:
    excerpts: list[str] = []
    remaining_chars = 1600
    for page in _pages_for_node(node, pages_by_index):
        if remaining_chars <= 0:
            break
        excerpt = page.text[:remaining_chars].strip()
        if excerpt:
            excerpts.append(excerpt)
            remaining_chars -= len(excerpt)
    return tuple(excerpts)


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
        if page.page_index < node.heading_anchor.page:
            continue
        if page.page_index > first_child.heading_anchor.page:
            break

        start_offset = (
            node.heading_anchor.end_offset if page.page_index == node.heading_anchor.page else 0
        )
        end_offset = len(page.text)
        if page.page_index == first_child.heading_anchor.page:
            end_offset = min(end_offset, first_child.heading_anchor.start_offset)
        if start_offset < end_offset:
            parts.append(page.text[start_offset:end_offset].strip())
    return "\n".join(part for part in parts if part).strip()


class NodeSummarizer:
    """Bottom-up committed-node summarizer."""

    def __init__(self, gateway: StructuredLLMGateway, max_workers: int = 4) -> None:
        self._gateway = gateway
        self._max_workers = max_workers
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
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                level_summaries = list(
                    executor.map(
                        lambda node: self._summarize_node(
                            node=node,
                            pages_by_index=pages_by_index,
                            children=children_by_parent.get(node.node_id, ()),
                            summaries_by_id=summaries_by_id,
                        ),
                        level_nodes,
                    )
                )
            for summary in level_summaries:
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
        if artifact_root is not None:
            self._artifact_path = _write_json(
                Path(artifact_root) / "summaries" / "node-summaries.json",
                ordered_summaries,
            )
        return tuple(ordered_nodes), node_cards, ordered_summaries

    def _summarize_node(
        self,
        *,
        node: HierarchyNode,
        pages_by_index: dict[int, PageArtifacts],
        children: tuple[HierarchyNode, ...],
        summaries_by_id: dict[str, NodeSummary],
    ) -> NodeSummary:
        if not children:
            raw_text = _node_raw_text(node, pages_by_index)
            token_count = estimate_token_count(raw_text)
            if token_count < LEAF_PASSTHROUGH_TOKEN_THRESHOLD:
                return NodeSummary(
                    node_id=node.node_id,
                    summary=raw_text or node.title,
                    summary_method=NodeSummaryMethod.PASSTHROUGH,
                    token_count=token_count,
                )
            response = self._gateway.invoke(
                GatewayRequest[SummarizationPromptResponse](
                    operation_name="summarize_leaf_node",
                    messages=build_summarization_messages(
                        node_title=node.title,
                        excerpts=_bounded_leaf_excerpts(node, pages_by_index),
                    ),
                    response_model=SummarizationPromptResponse,
                )
            )
            return NodeSummary(
                node_id=node.node_id,
                summary=response.output.summary,
                keywords=response.output.keywords,
                summary_method=NodeSummaryMethod.LLM_LEAF,
                token_count=token_count,
            )

        child_pairs = tuple(
            (child.title, summaries_by_id[child.node_id].summary)
            for child in sorted(children, key=_stable_node_order)
        )
        prefix_text = _parent_prefix_text(node, children, pages_by_index)
        token_count = estimate_token_count(
            prefix_text + "\n" + "\n".join(f"{title}: {summary}" for title, summary in child_pairs)
        )
        response = self._gateway.invoke(
            GatewayRequest[SummarizationPromptResponse](
                operation_name="summarize_parent_node",
                messages=build_summarization_messages(
                    node_title=node.title,
                    parent_prefix_text=prefix_text,
                    child_summaries=child_pairs,
                ),
                response_model=SummarizationPromptResponse,
            )
        )
        return NodeSummary(
            node_id=node.node_id,
            summary=response.output.summary,
            keywords=response.output.keywords,
            summary_method=NodeSummaryMethod.LLM_PARENT,
            token_count=token_count,
        )
