"""Query planner tests for LLM-driven and fallback query analysis."""

from __future__ import annotations

from nullvector.domain.retrieval import QueryIntent, RetrievalModality
from nullvector.retrieval import QueryPlanner


def test_fallback_planner_detects_visual_query() -> None:
    plan = QueryPlanner().plan("what is the image about?")

    assert plan.visual_query is True
    assert plan.query_intent is QueryIntent.VISUAL_LOOKUP
    assert RetrievalModality.VISUAL in plan.modality_filters
    assert plan.requires_multimodal is True


def test_fallback_planner_detects_table_query() -> None:
    plan = QueryPlanner().plan("show me the table")

    assert plan.table_query is True
    assert plan.query_intent is QueryIntent.TABLE_LOOKUP
    assert RetrievalModality.TABLE in plan.modality_filters


def test_fallback_planner_detects_structural_query() -> None:
    plan = QueryPlanner().plan("appendix A details")

    assert plan.structural_query is True
    assert plan.query_intent is QueryIntent.SECTION_LOOKUP


def test_fallback_planner_detects_document_summary() -> None:
    plan = QueryPlanner().plan("what is this document about?")

    assert plan.query_intent is QueryIntent.DOCUMENT_SUMMARY


def test_fallback_planner_default_is_topic_lookup() -> None:
    plan = QueryPlanner().plan("quarterly revenue growth")

    assert plan.query_intent is QueryIntent.TOPIC_LOOKUP
    assert plan.visual_query is False
    assert plan.table_query is False
    assert plan.structural_query is False


def test_fallback_planner_normalizes_query() -> None:
    plan = QueryPlanner().plan("  What Is  This  About  ")

    assert plan.raw_query == "What Is  This  About"  # NonEmptyStr strips whitespace
    assert plan.normalized_query == "what is this about"
