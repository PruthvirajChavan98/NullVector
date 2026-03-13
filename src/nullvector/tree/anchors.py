"""Source anchor extraction for committed Phase 02 hierarchy nodes."""

from __future__ import annotations

from nullvector.domain.models import HierarchyNode, NodeAnchor, PageSourceAnchor
from nullvector.tree.headings import (
    PageArtifacts,
    normalized_title_key,
    split_text_lines_with_offsets,
)


def node_anchor_to_source_anchor(anchor: NodeAnchor) -> PageSourceAnchor:
    """Project a node heading anchor into the shared source-anchor contract."""

    return PageSourceAnchor(
        page=anchor.page,
        start_offset=anchor.start_offset,
        end_offset=anchor.end_offset,
        quote=anchor.anchor_text,
    )


def find_first_content_anchor(
    node: HierarchyNode,
    pages: tuple[PageArtifacts, ...],
) -> PageSourceAnchor | None:
    """Return the first non-heading line within a node's page span, if one exists."""

    for page in pages:
        if page.page_index < node.page_span.start_page or page.page_index > node.page_span.end_page:
            continue
        for line in split_text_lines_with_offsets(page.text, page.page_index):
            if normalized_title_key(line.text) == node.normalized_title:
                continue
            return PageSourceAnchor(
                page=line.page_index,
                start_offset=line.start_offset,
                end_offset=line.end_offset,
                quote=line.text,
            )
    return None


def attach_content_anchors(
    nodes: tuple[HierarchyNode, ...],
    pages: tuple[PageArtifacts, ...],
) -> tuple[HierarchyNode, ...]:
    """Attach heading and first-content anchors to committed hierarchy nodes."""

    enriched_nodes: list[HierarchyNode] = []
    for node in nodes:
        heading_anchor = node_anchor_to_source_anchor(node.heading_anchor)
        content_anchor = find_first_content_anchor(node, pages)
        anchors = (heading_anchor,) if content_anchor is None else (heading_anchor, content_anchor)
        enriched_nodes.append(node.model_copy(update={"source_anchors": anchors}))
    return tuple(enriched_nodes)
