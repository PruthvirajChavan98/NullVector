"""Retrieval ranking tests."""

from __future__ import annotations

from nullvector.domain.common import PageSpan
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalEvidence,
    RetrievalModality,
    RetrievalUnitType,
)
from nullvector.retrieval import QueryPlanner, RetrievalRanker


def test_page_filtered_visual_query_ranks_page_zero_visual_above_text_nodes() -> None:
    ranker = RetrievalRanker()
    plan = QueryPlanner().plan("what is the image on first page about?")
    visual = RetrievalEvidence(
        unit_id="visual-0",
        document_id="d" * 64,
        unit_type=RetrievalUnitType.VISUAL,
        modality=RetrievalModality.VISUAL,
        page_span=PageSpan(start_page=0, end_page=0),
        authoritative=False,
    )
    page_text = RetrievalEvidence(
        unit_id="page-text-0",
        document_id="d" * 64,
        unit_type=RetrievalUnitType.PAGE_TEXT,
        modality=RetrievalModality.TEXT,
        page_span=PageSpan(start_page=0, end_page=0),
        text="Cover page title only.",
        authoritative=True,
    )
    node_text = RetrievalEvidence(
        unit_id="node-text-1",
        document_id="d" * 64,
        unit_type=RetrievalUnitType.NODE_TEXT,
        modality=RetrievalModality.TEXT,
        page_span=PageSpan(start_page=1, end_page=1),
        text="Alpha body line",
        authoritative=True,
    )

    hits = ranker.rank(
        query="what is the image on first page about?",
        plan=plan,
        candidates=(page_text, node_text, visual),
    )

    assert hits[0].unit.unit_id == "visual-0"
    assert hits[0].score > hits[1].score


def test_summary_unit_does_not_outrank_exact_page_text() -> None:
    ranker = RetrievalRanker()
    plan = QueryPlan(
        raw_query="Alpha body line",
        normalized_query="alpha body line",
    )
    page_text = RetrievalEvidence(
        unit_id="page-text",
        document_id="d" * 64,
        unit_type=RetrievalUnitType.PAGE_TEXT,
        modality=RetrievalModality.TEXT,
        page_span=PageSpan(start_page=1, end_page=1),
        text="Alpha body line",
        authoritative=True,
    )
    summary = RetrievalEvidence(
        unit_id="node-summary",
        document_id="d" * 64,
        unit_type=RetrievalUnitType.NODE_SUMMARY,
        modality=RetrievalModality.TEXT,
        page_span=PageSpan(start_page=1, end_page=1),
        text="Alpha body line is summarized here.",
        interpretive=True,
        authoritative=False,
    )

    hits = ranker.rank(query="Alpha body line", plan=plan, candidates=(summary, page_text))

    assert hits[0].unit.unit_id == "page-text"
