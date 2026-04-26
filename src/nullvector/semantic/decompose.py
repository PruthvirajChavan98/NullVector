"""LLM-driven large-node decomposition over normalized synthesis text."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from nullvector._text import normalized_text_key
from nullvector.domain.common import ContentSpan, NodeOwnedSpan, PageSpan
from nullvector.domain.gateway import DecompositionPromptResponse
from nullvector.domain.tree import (
    DecompositionBoundary,
    DecompositionMethod,
    DecompositionReport,
    HierarchyNode,
    HierarchyOrigin,
    SemanticUsage,
    TreeSettings,
)
from nullvector.llm.prompts import build_decomposition_messages
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest, GatewayUsage
from nullvector.semantic._text_spans import _TextPage, text_for_node
from nullvector.storage._serialization import write_json_file
from nullvector.tree.hierarchy import generate_node_id
from nullvector.tree.page_data import PageData as PageArtifacts

_MAX_LLM_PAGE_TEXT_CHARS = 12000


@dataclass(frozen=True)
class _DecompositionMetadata:
    provider_name: str
    assurance_mode: str
    usage: SemanticUsage | None
    audit_path: str | None


def _stable_node_order(node: HierarchyNode) -> tuple[int, int, str]:
    return (node.page_span.start_page, node.level, node.node_id)


def _usage_snapshot(usage: GatewayUsage | None) -> SemanticUsage | None:
    if usage is None:
        return None
    return SemanticUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def _combine_usage(left: SemanticUsage | None, right: SemanticUsage | None) -> SemanticUsage | None:
    if left is None:
        return right
    if right is None:
        return left
    return SemanticUsage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
    )


def _node_pages(
    node: HierarchyNode, pages_by_index: dict[int, PageArtifacts]
) -> tuple[PageArtifacts, ...]:
    return tuple(
        pages_by_index[i]
        for i in range(node.page_span.start_page, node.page_span.end_page + 1)
        if i in pages_by_index
    )


def _is_leaf(node: HierarchyNode, parent_ids: set[str]) -> bool:
    return node.node_id not in parent_ids


def _candidate_level(parent: HierarchyNode, level_hint: int | None) -> int:
    if level_hint is not None and level_hint > parent.level:
        return level_hint
    return parent.level + 1


def _bounded_llm_node_text(node: HierarchyNode, pages_by_index: dict[int, PageArtifacts]) -> str:
    return text_for_node(node, cast(Mapping[int, _TextPage], pages_by_index))[
        :_MAX_LLM_PAGE_TEXT_CHARS
    ].strip()


def _owned_spans_are_empty(node: HierarchyNode) -> bool:
    if not node.owned_spans:
        return True
    return all(
        span.span.start_page == span.span.end_page
        and span.span.start_offset == span.span.end_offset
        for span in node.owned_spans
    )


class NodeDecomposer:
    """LLM-driven decomposition of large leaf nodes."""

    def __init__(
        self,
        settings: TreeSettings,
        gateway: StructuredLLMGateway | None = None,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._artifact_path: str | None = None

    @property
    def artifact_path(self) -> str | None:
        return self._artifact_path

    def decompose(
        self,
        *,
        nodes: tuple[HierarchyNode, ...],
        pages: tuple[PageArtifacts, ...],
        tree_run_id: str,
        artifact_root: str | None = None,
        artifact_writer: Callable[[str, Any], str] | None = None,
    ) -> tuple[tuple[HierarchyNode, ...], DecompositionReport]:
        del tree_run_id
        pages_by_index = {page.page_index: page for page in pages}
        current_nodes = tuple(sorted(nodes, key=_stable_node_order))
        decomposed_node_ids: list[str] = []
        new_child_count = 0
        empty_parent_count = 0
        max_depth_used = 0
        provider_name: str | None = None
        assurance_mode: str | None = None
        gateway_usage: SemanticUsage | None = None
        gateway_audit_paths: list[str] = []

        for depth in range(1, self._settings.max_decomposition_depth + 1):
            parent_ids = {n.parent_id for n in current_nodes if n.parent_id is not None}
            depth_changed = False
            next_nodes = list(current_nodes)

            for node in list(current_nodes):
                if not _is_leaf(node, parent_ids):
                    continue
                if not self._needs_decomposition(node):
                    continue
                if self._gateway is None:
                    continue

                result = self._llm_decompose(node=node, pages_by_index=pages_by_index)
                if result is None:
                    continue

                truncated_parent, children, metadata = result
                next_nodes = [n for n in next_nodes if n.node_id != node.node_id]
                next_nodes.append(truncated_parent)
                next_nodes.extend(children)
                decomposed_node_ids.append(node.node_id)
                new_child_count += len(children)
                if _owned_spans_are_empty(truncated_parent):
                    empty_parent_count += 1
                provider_name = metadata.provider_name
                assurance_mode = metadata.assurance_mode
                gateway_usage = _combine_usage(gateway_usage, metadata.usage)
                if metadata.audit_path is not None:
                    gateway_audit_paths.append(metadata.audit_path)
                depth_changed = True

            current_nodes = tuple(sorted(next_nodes, key=_stable_node_order))
            if depth_changed:
                max_depth_used = depth
                continue
            break

        method = (
            DecompositionMethod.LLM_ASSISTED if new_child_count > 0 else DecompositionMethod.NONE
        )
        report = DecompositionReport(
            decomposed_node_ids=tuple(decomposed_node_ids),
            new_child_count=new_child_count,
            empty_parent_count=empty_parent_count,
            decomposition_method=method,
            depth=max_depth_used,
            gateway_provider_name=provider_name,
            gateway_assurance_mode=assurance_mode,
            gateway_usage=gateway_usage,
            gateway_audit_paths=tuple(gateway_audit_paths),
        )
        if artifact_writer is not None:
            self._artifact_path = artifact_writer("decomposition/report.json", report)
        elif artifact_root is not None:
            self._artifact_path = write_json_file(
                Path(artifact_root) / "decomposition" / "report.json", report
            )
        return current_nodes, report

    def _needs_decomposition(self, node: HierarchyNode) -> bool:
        page_count = node.page_span.end_page - node.page_span.start_page + 1
        return page_count > self._settings.max_pages_per_leaf_node

    def _llm_decompose(
        self,
        *,
        node: HierarchyNode,
        pages_by_index: dict[int, PageArtifacts],
    ) -> tuple[HierarchyNode, tuple[HierarchyNode, ...], _DecompositionMetadata] | None:
        if self._gateway is None:
            return None
        pages = _node_pages(node, pages_by_index)
        response = self._gateway.invoke(
            GatewayRequest[DecompositionPromptResponse](
                operation_name="decompose_large_node",
                messages=build_decomposition_messages(
                    node_title=node.title,
                    page_text=_bounded_llm_node_text(node, pages_by_index),
                ),
                response_model=DecompositionPromptResponse,
            )
        )
        children = self._children_from_boundaries(
            node=node,
            boundaries=response.output.entries,
            pages=pages,
        )
        if len(children) < 2:
            return None
        truncated_parent = self._refine_parent_owned_spans(node, children)
        metadata = _DecompositionMetadata(
            provider_name=response.provider_name,
            assurance_mode=response.assurance_mode.value,
            usage=_usage_snapshot(response.usage),
            audit_path=response.audit_path,
        )
        return truncated_parent, children, metadata

    def _children_from_boundaries(
        self,
        *,
        node: HierarchyNode,
        boundaries: tuple[DecompositionBoundary, ...],
        pages: tuple[PageArtifacts, ...],
    ) -> tuple[HierarchyNode, ...]:
        if len(boundaries) < 2:
            return ()

        children: list[HierarchyNode] = []
        parent_end_page = node.page_span.end_page
        sorted_boundaries = sorted(boundaries, key=lambda b: (b.page_index, b.title))

        for index, boundary in enumerate(sorted_boundaries):
            has_next = index + 1 < len(sorted_boundaries)
            next_boundary = sorted_boundaries[index + 1] if has_next else None
            child_end_page = (
                next_boundary.page_index if next_boundary is not None else parent_end_page
            )

            level = _candidate_level(node, boundary.level_hint)
            title = boundary.title.strip()
            path = (*node.path, title)
            child = HierarchyNode(
                node_id=generate_node_id(
                    document_id=node.document_id,
                    path=path,
                    level=level,
                    page=boundary.page_index,
                    start_offset=0,
                    end_offset=1,
                    span_start_page=boundary.page_index,
                ),
                document_id=node.document_id,
                parent_id=node.node_id,
                path=path,
                level=level,
                title=title,
                normalized_title=normalized_text_key(title),
                page_span=PageSpan(
                    start_page=boundary.page_index,
                    end_page=max(boundary.page_index, child_end_page),
                ),
                origin=HierarchyOrigin.LLM_SYNTHESIZED,
                confidence=0.6,
            )
            children.append(child)
        return tuple(children)

    def _refine_parent_owned_spans(
        self,
        node: HierarchyNode,
        children: tuple[HierarchyNode, ...],
    ) -> HierarchyNode:
        first_child = min(children, key=_stable_node_order)
        if node.owned_spans:
            parent_start_page = node.owned_spans[0].span.start_page
            parent_start_offset = node.owned_spans[0].span.start_offset
        else:
            parent_start_page = node.page_span.start_page
            parent_start_offset = 0
        prefix_end_page = first_child.page_span.start_page

        if prefix_end_page < parent_start_page:
            return node.model_copy(update={"owned_spans": ()})

        return node.model_copy(
            update={
                "owned_spans": (
                    NodeOwnedSpan(
                        kind="body",
                        span=ContentSpan(
                            start_page=parent_start_page,
                            start_offset=parent_start_offset,
                            end_page=prefix_end_page,
                            end_offset=0,
                        ),
                    ),
                )
            }
        )


__all__ = [
    "NodeDecomposer",
]
