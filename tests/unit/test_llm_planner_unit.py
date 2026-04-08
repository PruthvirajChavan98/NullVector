"""Unit tests for the LLM query planner and prompt builder."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.retrieval import QueryIntent
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.llm.prompts.query_planning import (
    QueryPlanningResponse,
    build_query_planning_messages,
)
from nullvector.llm.types import LLMRole
from nullvector.retrieval.llm_planner import LLMQueryPlanner


def test_build_messages_returns_system_and_user() -> None:
    messages = build_query_planning_messages("what is the image?")
    assert len(messages) == 2
    assert messages[0].role is LLMRole.SYSTEM
    assert messages[1].role is LLMRole.USER


def test_user_message_includes_query() -> None:
    messages = build_query_planning_messages("revenue growth")
    assert "revenue growth" in messages[1].content


def test_response_model_defaults() -> None:
    response = QueryPlanningResponse()
    assert response.intent == "topic_lookup"
    assert response.visual_query is False
    assert response.page_filter_start is None


def test_gateway_planner_returns_structured_plan(tmp_path: Path) -> None:
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "query_planning": NoopScriptedResponse(
                    output_json={
                        "intent": "visual_lookup",
                        "page_filter_start": 0,
                        "page_filter_end": 0,
                        "structural_query": False,
                        "visual_query": True,
                        "table_query": False,
                        "title_phrases": [],
                        "quoted_phrases": [],
                    }
                ),
            }
        ),
    )
    planner = LLMQueryPlanner(gateway=gateway)
    plan = planner.plan("what is the image on page 1?")

    assert plan.query_intent is QueryIntent.VISUAL_LOOKUP
    assert plan.visual_query is True
    assert plan.page_filter is not None
    assert plan.page_filter.start_page == 0


def test_fallback_planner_handles_unknown_intent() -> None:
    planner = LLMQueryPlanner(gateway=None)
    plan = planner.plan("something random")

    assert plan.query_intent is QueryIntent.TOPIC_LOOKUP
    assert plan.normalized_query == "something random"
