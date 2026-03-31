"""Query planner tests for deterministic page and modality extraction."""

from __future__ import annotations

from nullvector.domain.retrieval import QueryIntent, RetrievalModality, RetrievalUnitType
from nullvector.retrieval import QueryPlanner


def test_query_planner_detects_first_page_image_query() -> None:
    plan = QueryPlanner().plan("what is the image on first page about?")

    assert plan.page_filter is not None
    assert plan.page_filter.start_page == 0
    assert plan.page_filter.end_page == 0
    assert plan.modality_filters == (RetrievalModality.VISUAL,)
    assert plan.unit_types == (
        RetrievalUnitType.VISUAL,
        RetrievalUnitType.UNRESOLVED_VISUAL,
    )
    assert plan.visual_query is True
    assert plan.requires_multimodal is True


def test_query_planner_detects_page_12_table_query() -> None:
    plan = QueryPlanner().plan("show me the table on page 12")

    assert plan.page_filter is not None
    assert plan.page_filter.start_page == 11
    assert plan.modality_filters == (RetrievalModality.TABLE,)
    assert plan.unit_types == (RetrievalUnitType.TABLE,)
    assert plan.table_query is True


def test_query_planner_detects_appendix_a_as_structural_query() -> None:
    plan = QueryPlanner().plan("appendix A")

    assert plan.structural_query is True
    assert "appendix a" in plan.title_like_phrases


def test_query_planner_extracts_quoted_title_phrases() -> None:
    plan = QueryPlanner().plan('where is "Safety Overview" discussed?')

    assert plan.structural_query is True
    assert plan.query_intent is QueryIntent.QUOTE_LOOKUP
    assert plan.quoted_phrases == ("safety overview",)
    assert "safety overview" in plan.title_like_phrases


def test_query_planner_detects_document_summary_queries() -> None:
    plan = QueryPlanner().plan("what is this book about?")

    assert plan.query_intent is QueryIntent.DOCUMENT_SUMMARY
    assert plan.structural_query is False
    assert plan.page_filter is None
    assert RetrievalUnitType.NODE_SUMMARY in plan.unit_types
