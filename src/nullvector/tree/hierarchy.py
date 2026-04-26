"""Architecture-neutral hierarchy utilities: node ID generation, card projection, span gaps."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from nullvector.domain.common import ContentSpan, NodeOwnedSpan, PageSpan
from nullvector.domain.tree import (
    HierarchyNode,
    NodeCard,
    UnassignedPageSpan,
)


def normalize_path_segment(value: str) -> str:
    """Normalize a path segment for stable hashing and rerun diffs."""

    return " ".join(value.split()).casefold()


def generate_node_id(
    document_id: str,
    path: tuple[str, ...],
    level: int,
    page: int,
    start_offset: int,
    end_offset: int,
    span_start_page: int,
) -> str:
    """Create a stable node id from document/path/anchor/span-start inputs."""

    normalized_path = "|".join(normalize_path_segment(segment) for segment in path)
    payload = (
        f"{document_id}|{normalized_path}|{level}|"
        f"{page}|{start_offset}|{end_offset}|{span_start_page}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_unassigned_spans(
    *,
    document_id: str,
    page_count: int,
    nodes: Sequence[HierarchyNode],
) -> tuple[UnassignedPageSpan, ...]:
    """Emit explicit coverage gaps instead of inventing a synthetic root node."""

    covered = [False] * page_count
    for node in nodes:
        for page_index in range(node.page_span.start_page, node.page_span.end_page + 1):
            covered[page_index] = True

    first_covered = next((index for index, is_covered in enumerate(covered) if is_covered), None)
    last_covered = next(
        (index for index in range(page_count - 1, -1, -1) if covered[index]),
        None,
    )
    spans: list[UnassignedPageSpan] = []
    span_start: int | None = None
    for index, is_covered in enumerate(covered):
        if not is_covered and span_start is None:
            span_start = index
        if is_covered and span_start is not None:
            spans.append(
                UnassignedPageSpan(
                    document_id=document_id,
                    reason=_gap_reason(span_start, index - 1, first_covered, last_covered),
                    page_span=PageSpan(start_page=span_start, end_page=index - 1),
                ),
            )
            span_start = None
    if span_start is not None:
        spans.append(
            UnassignedPageSpan(
                document_id=document_id,
                reason=_gap_reason(span_start, page_count - 1, first_covered, last_covered),
                page_span=PageSpan(start_page=span_start, end_page=page_count - 1),
            ),
        )
    return tuple(spans)


def _gap_reason(
    start_page: int,
    end_page: int,
    first_covered: int | None,
    last_covered: int | None,
) -> str:
    if first_covered is None:
        return "no_verified_headings"
    if last_covered is None:
        return "no_verified_headings"
    if end_page < first_covered:
        return "before_first_heading"
    if start_page > last_covered:
        return "after_last_heading"
    return "between_verified_nodes"


def project_node_cards(nodes: Sequence[HierarchyNode]) -> tuple[NodeCard, ...]:
    """Project internal hierarchy nodes into the committed public NodeCard contract."""

    return tuple(
        NodeCard(
            node_id=node.node_id,
            document_id=node.document_id,
            path=node.path,
            level=node.level,
            title=node.title,
            page_span=node.page_span,
            owned_spans=node.owned_spans,
            source_anchors=node.source_anchors,
        )
        for node in nodes
    )


def attach_default_owned_spans(
    nodes: Sequence[HierarchyNode],
    page_lengths: dict[int, int],
) -> tuple[HierarchyNode, ...]:
    """Attach coarse default ownership spans before decomposition refines them."""

    updated: list[HierarchyNode] = []
    for node in nodes:
        end_offset = page_lengths.get(node.page_span.end_page, 0)
        updated.append(
            node.model_copy(
                update={
                    "owned_spans": (
                        NodeOwnedSpan(
                            kind="body",
                            span=ContentSpan(
                                start_page=node.page_span.start_page,
                                start_offset=0,
                                end_page=node.page_span.end_page,
                                end_offset=end_offset,
                            ),
                        ),
                    )
                }
            )
        )
    return tuple(updated)


__all__ = [
    "attach_default_owned_spans",
    "compute_unassigned_spans",
    "generate_node_id",
    "normalize_path_segment",
    "project_node_cards",
]
