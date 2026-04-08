"""Retrieval ranking tests for LLM-driven and fallback ranker."""

from __future__ import annotations

from nullvector.domain.common import PageSpan
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalEvidence,
    RetrievalModality,
    RetrievalUnitType,
)
from nullvector.retrieval import RetrievalRanker


def test_fallback_ranker_ranks_by_keyword_overlap() -> None:
    ranker = RetrievalRanker()
    plan = QueryPlan(
        raw_query="alpha revenue growth",
        normalized_query="alpha revenue growth",
    )
    relevant = RetrievalEvidence(
        unit_id="relevant",
        document_id="d" * 64,
        unit_type=RetrievalUnitType.NODE_TEXT,
        modality=RetrievalModality.TEXT,
        page_span=PageSpan(start_page=0, end_page=0),
        text="Alpha revenue growth accelerated this quarter.",
        authoritative=True,
    )
    irrelevant = RetrievalEvidence(
        unit_id="irrelevant",
        document_id="d" * 64,
        unit_type=RetrievalUnitType.NODE_TEXT,
        modality=RetrievalModality.TEXT,
        page_span=PageSpan(start_page=1, end_page=1),
        text="Beta litigation policies were updated.",
        authoritative=True,
    )

    hits = ranker.rank(
        query="alpha revenue growth",
        plan=plan,
        candidates=(irrelevant, relevant),
    )

    assert hits[0].unit.unit_id == "relevant"
    assert hits[0].score > hits[1].score


def test_fallback_ranker_returns_matched_terms() -> None:
    ranker = RetrievalRanker()
    plan = QueryPlan(
        raw_query="revenue",
        normalized_query="revenue",
    )
    candidate = RetrievalEvidence(
        unit_id="match",
        document_id="d" * 64,
        unit_type=RetrievalUnitType.NODE_TEXT,
        modality=RetrievalModality.TEXT,
        page_span=PageSpan(start_page=0, end_page=0),
        text="Revenue growth was strong.",
        authoritative=True,
    )

    hits = ranker.rank(query="revenue", plan=plan, candidates=(candidate,))

    assert len(hits) == 1
    assert "revenue" in hits[0].matched_terms


def test_fallback_ranker_handles_empty_candidates() -> None:
    ranker = RetrievalRanker()
    plan = QueryPlan(raw_query="test", normalized_query="test")

    hits = ranker.rank(query="test", plan=plan, candidates=())

    assert hits == ()
