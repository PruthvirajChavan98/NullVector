"""Unit tests for the LLM retrieval ranker and prompt builder."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.common import PageSpan
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalEvidence,
    RetrievalModality,
    RetrievalUnitType,
)
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.llm.prompts.retrieval_ranking import (
    RetrievalRankingResponse,
    build_retrieval_ranking_messages,
)
from nullvector.llm.types import LLMRole
from nullvector.retrieval.llm_ranker import LLMRetrievalRanker


def _candidate(unit_id: str, text: str) -> RetrievalEvidence:
    return RetrievalEvidence(
        unit_id=unit_id,
        document_id="d" * 64,
        unit_type=RetrievalUnitType.NODE_TEXT,
        modality=RetrievalModality.TEXT,
        page_span=PageSpan(start_page=0, end_page=0),
        text=text,
        authoritative=True,
    )


def test_build_messages_returns_system_and_user() -> None:
    messages = build_retrieval_ranking_messages(
        query="test",
        candidate_summaries=({"id": "a", "title": "A", "text": "content"},),
    )
    assert len(messages) == 2
    assert messages[0].role is LLMRole.SYSTEM
    assert messages[1].role is LLMRole.USER


def test_user_message_includes_query_and_candidates() -> None:
    messages = build_retrieval_ranking_messages(
        query="revenue growth",
        candidate_summaries=({"id": "c1", "title": "Rev", "text": "growth"},),
    )
    assert "revenue growth" in messages[1].content
    assert "c1" in messages[1].content


def test_response_model_defaults() -> None:
    response = RetrievalRankingResponse()
    assert response.ranked_ids == ()
    assert response.scores == ()


def test_gateway_ranker_returns_scored_hits(tmp_path: Path) -> None:
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "retrieval_ranking": NoopScriptedResponse(
                    output_json={
                        "ranked_ids": ["relevant", "irrelevant"],
                        "scores": [0.9, 0.1],
                    }
                ),
            }
        ),
    )
    ranker = LLMRetrievalRanker(gateway=gateway)
    plan = QueryPlan(raw_query="test", normalized_query="test")
    hits = ranker.rank(
        query="test",
        plan=plan,
        candidates=(
            _candidate("irrelevant", "unrelated text"),
            _candidate("relevant", "test content"),
        ),
    )

    assert hits[0].unit.unit_id == "relevant"
    assert hits[0].score == 0.9
    assert hits[1].unit.unit_id == "irrelevant"
    assert hits[1].score == 0.1


def test_fallback_ranker_uses_keyword_overlap() -> None:
    ranker = LLMRetrievalRanker(gateway=None)
    plan = QueryPlan(raw_query="alpha", normalized_query="alpha")
    hits = ranker.rank(
        query="alpha",
        plan=plan,
        candidates=(
            _candidate("miss", "beta gamma delta"),
            _candidate("match", "alpha content here"),
        ),
    )

    assert hits[0].unit.unit_id == "match"
    assert hits[0].score > hits[1].score
    assert "alpha" in hits[0].matched_terms


def test_empty_candidates_returns_empty() -> None:
    ranker = LLMRetrievalRanker(gateway=None)
    plan = QueryPlan(raw_query="test", normalized_query="test")
    assert ranker.rank(query="test", plan=plan, candidates=()) == ()
