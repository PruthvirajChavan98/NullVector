"""LLM-driven hierarchy builder for VLM-transcribed documents."""

from __future__ import annotations

from nullvector._text import normalized_text_key
from nullvector.domain.common import PageSpan
from nullvector.domain.gateway import HierarchySynthesisResponse
from nullvector.domain.ledger import OutlineEntry
from nullvector.domain.tree import (
    HierarchyBuildReport,
    HierarchyNode,
    HierarchyOrigin,
    NodeCard,
    UnassignedPageSpan,
)
from nullvector.llm.prompts.hierarchy_synthesis import build_hierarchy_synthesis_messages
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest
from nullvector.tree.hierarchy import (
    compute_unassigned_spans,
    generate_node_id,
    project_node_cards,
)


def _build_nodes_from_response(
    response: HierarchySynthesisResponse,
    *,
    document_id: str,
    page_count: int,
) -> tuple[HierarchyNode, ...]:
    """Convert LLM synthesis response into HierarchyNode objects."""

    nodes: list[HierarchyNode] = []
    path_stack: list[str] = []

    for synth_node in response.nodes:
        while len(path_stack) >= synth_node.level:
            path_stack.pop()
        path_stack.append(synth_node.title)
        path = tuple(path_stack)

        start_page = min(synth_node.start_page, page_count - 1)
        end_page = min(synth_node.end_page, page_count - 1)

        node_id = generate_node_id(
            document_id,
            path,
            synth_node.level,
            start_page,
            0,
            1,
            start_page,
        )

        nodes.append(
            HierarchyNode(
                node_id=node_id,
                document_id=document_id,
                parent_id=None,
                path=path,
                level=synth_node.level,
                title=synth_node.title,
                normalized_title=normalized_text_key(synth_node.title),
                page_span=PageSpan(start_page=start_page, end_page=end_page),
                origin=HierarchyOrigin.LLM_SYNTHESIZED,
                confidence=0.8,
            )
        )

    # Assign parent_ids based on path hierarchy
    node_by_path: dict[tuple[str, ...], str] = {}
    updated: list[HierarchyNode] = []
    for node in nodes:
        parent_path = node.path[:-1]
        parent_id = node_by_path.get(parent_path)
        node_by_path[node.path] = node.node_id
        updated.append(node.model_copy(update={"parent_id": parent_id}) if parent_id else node)

    return tuple(updated)


def _build_fallback_from_outline(
    *,
    document_id: str,
    page_count: int,
    outline_entries: tuple[OutlineEntry, ...],
) -> tuple[HierarchyNode, ...]:
    """Build a hierarchy from outline entries when no gateway is available."""

    if not outline_entries:
        title = "Document Root"
        path = (title,)
        node_id = generate_node_id(document_id, path, 1, 0, 0, 1, 0)
        return (
            HierarchyNode(
                node_id=node_id,
                document_id=document_id,
                path=path,
                level=1,
                title=title,
                normalized_title=normalized_text_key(title),
                page_span=PageSpan(start_page=0, end_page=max(0, page_count - 1)),
                origin=HierarchyOrigin.INFERRED,
                confidence=0.5,
            ),
        )

    nodes: list[HierarchyNode] = []
    sorted_entries = sorted(outline_entries, key=lambda e: (e.page_index, e.level, e.title))
    path_stack: list[str] = []

    for i, entry in enumerate(sorted_entries):
        while len(path_stack) >= entry.level:
            path_stack.pop()
        path_stack.append(entry.title)
        path = tuple(path_stack)

        start_page = min(entry.page_index, page_count - 1)
        if i + 1 < len(sorted_entries):
            end_page = min(sorted_entries[i + 1].page_index, page_count - 1)
        else:
            end_page = page_count - 1

        node_id = generate_node_id(document_id, path, entry.level, start_page, 0, 1, start_page)
        nodes.append(
            HierarchyNode(
                node_id=node_id,
                document_id=document_id,
                path=path,
                level=entry.level,
                title=entry.title,
                normalized_title=normalized_text_key(entry.title),
                page_span=PageSpan(start_page=start_page, end_page=end_page),
                origin=HierarchyOrigin.OUTLINE,
                confidence=0.7,
            )
        )

    # Assign parent_ids
    node_by_path: dict[tuple[str, ...], str] = {}
    updated: list[HierarchyNode] = []
    for node in nodes:
        parent_path = node.path[:-1]
        parent_id = node_by_path.get(parent_path)
        node_by_path[node.path] = node.node_id
        updated.append(node.model_copy(update={"parent_id": parent_id}) if parent_id else node)

    return tuple(updated)


class LLMHierarchyBuilder:
    """Builds a document hierarchy using LLM synthesis from VLM Markdown."""

    def __init__(self, gateway: StructuredLLMGateway | None = None) -> None:
        self._gateway = gateway

    def build(
        self,
        *,
        document_id: str,
        tree_run_id: str,
        markdown_pages: tuple[str, ...],
        outline_entries: tuple[OutlineEntry, ...] = (),
    ) -> tuple[
        tuple[HierarchyNode, ...],
        tuple[NodeCard, ...],
        tuple[UnassignedPageSpan, ...],
        HierarchyBuildReport,
    ]:
        """Synthesize a hierarchy and return nodes, cards, gaps, and report."""

        page_count = len(markdown_pages)

        if self._gateway is not None:
            messages = build_hierarchy_synthesis_messages(
                markdown_pages=markdown_pages,
                outline_entries=outline_entries,
            )
            request: GatewayRequest[HierarchySynthesisResponse] = GatewayRequest(
                operation_name="hierarchy_synthesis",
                messages=messages,
                response_model=HierarchySynthesisResponse,
                temperature=0.0,
            )
            result = self._gateway.invoke(request)
            committed_nodes = _build_nodes_from_response(
                result.output,
                document_id=document_id,
                page_count=page_count,
            )
            synthesis_method = "llm"
        else:
            committed_nodes = _build_fallback_from_outline(
                document_id=document_id,
                page_count=page_count,
                outline_entries=outline_entries,
            )
            synthesis_method = "outline_fallback" if outline_entries else "fallback_single_node"

        node_cards = project_node_cards(committed_nodes)
        unassigned_spans = compute_unassigned_spans(
            document_id=document_id,
            page_count=page_count,
            nodes=committed_nodes,
        )

        report = HierarchyBuildReport(
            document_id=document_id,
            tree_run_id=tree_run_id,
            committed_node_count=len(committed_nodes),
            unassigned_span_count=len(unassigned_spans),
            synthesis_method=synthesis_method,
        )

        return committed_nodes, node_cards, unassigned_spans, report


__all__ = [
    "LLMHierarchyBuilder",
]
