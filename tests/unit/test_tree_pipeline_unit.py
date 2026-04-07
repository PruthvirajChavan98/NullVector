"""Unit tests for Phase 02 tree pipeline helpers that survived the VLM pivot."""

from __future__ import annotations

from nullvector.domain.common import PageSpan
from nullvector.domain.tree import HierarchyNode, HierarchyOrigin
from nullvector.tree.hierarchy import compute_unassigned_spans, generate_node_id

DOC_ID = "d" * 64


def _node(title: str, start_page: int, end_page: int) -> HierarchyNode:
    path = (title,)
    return HierarchyNode(
        node_id=generate_node_id(DOC_ID, path, 1, start_page, 0, 1, start_page),
        document_id=DOC_ID,
        path=path,
        level=1,
        title=title,
        normalized_title=title.casefold(),
        page_span=PageSpan(start_page=start_page, end_page=end_page),
        origin=HierarchyOrigin.INFERRED,
        confidence=0.5,
    )


def test_generate_node_id_is_stable() -> None:
    first = generate_node_id(
        document_id=DOC_ID,
        path=("Root", "Child"),
        level=2,
        page=3,
        start_offset=10,
        end_offset=20,
        span_start_page=3,
    )
    second = generate_node_id(
        document_id=DOC_ID,
        path=("Root", "Child"),
        level=2,
        page=3,
        start_offset=10,
        end_offset=20,
        span_start_page=3,
    )

    assert first == second


def test_unassigned_page_count_sums_page_coverage_not_span_count() -> None:
    """Two separate gaps of 1 page each = 2 unassigned spans covering 2 pages total."""

    nodes = (
        _node("A", start_page=1, end_page=1),
        _node("B", start_page=3, end_page=3),
    )
    spans = compute_unassigned_spans(document_id=DOC_ID, page_count=5, nodes=nodes)

    total_unassigned_pages = sum(
        span.page_span.end_page - span.page_span.start_page + 1 for span in spans
    )
    assert len(spans) == 3  # pages 0, 2, 4
    assert total_unassigned_pages == 3


def test_unassigned_spans_empty_when_full_coverage() -> None:
    nodes = (_node("Full", start_page=0, end_page=2),)
    spans = compute_unassigned_spans(document_id=DOC_ID, page_count=3, nodes=nodes)

    assert len(spans) == 0


def test_unassigned_spans_covers_all_when_no_nodes() -> None:
    spans = compute_unassigned_spans(document_id=DOC_ID, page_count=4, nodes=())

    assert len(spans) == 1
    assert spans[0].page_span.start_page == 0
    assert spans[0].page_span.end_page == 3
    assert spans[0].reason == "no_verified_headings"
