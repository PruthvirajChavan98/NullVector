"""LLM-driven query planner for retrieval."""

from __future__ import annotations

from nullvector._text import normalize_text
from nullvector.domain.common import PageSpan
from nullvector.domain.retrieval import (
    QueryIntent,
    QueryPlan,
    RetrievalModality,
)
from nullvector.llm.prompts.query_planning import (
    QueryPlanningResponse,
    build_query_planning_messages,
)
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest

_INTENT_MAP: dict[str, QueryIntent] = {
    "topic_lookup": QueryIntent.TOPIC_LOOKUP,
    "document_summary": QueryIntent.DOCUMENT_SUMMARY,
    "visual_lookup": QueryIntent.VISUAL_LOOKUP,
    "table_lookup": QueryIntent.TABLE_LOOKUP,
    "page_lookup": QueryIntent.PAGE_LOOKUP,
    "quote_lookup": QueryIntent.QUOTE_LOOKUP,
    "section_lookup": QueryIntent.SECTION_LOOKUP,
}


class LLMQueryPlanner:
    """LLM-driven query planner with deterministic fallback."""

    def __init__(self, gateway: StructuredLLMGateway | None = None) -> None:
        self._gateway = gateway

    def plan(self, query: str) -> QueryPlan:
        """Analyze a query and produce a structured retrieval plan."""

        normalized = normalize_text(query)

        if self._gateway is not None:
            return self._llm_plan(query, normalized)
        return self._fallback_plan(query, normalized)

    def _llm_plan(self, query: str, normalized: str) -> QueryPlan:
        messages = build_query_planning_messages(query)
        request: GatewayRequest[QueryPlanningResponse] = GatewayRequest(
            operation_name="query_planning",
            messages=messages,
            response_model=QueryPlanningResponse,
            temperature=0.0,
        )
        result = self._gateway.invoke(request)  # type: ignore[union-attr]
        response = result.output

        intent = _INTENT_MAP.get(response.intent, QueryIntent.TOPIC_LOOKUP)
        page_filter = None
        if response.page_filter_start is not None:
            page_filter = PageSpan(
                start_page=response.page_filter_start,
                end_page=response.page_filter_end or response.page_filter_start,
            )

        modality_filters: list[RetrievalModality] = []
        if response.visual_query:
            modality_filters.append(RetrievalModality.VISUAL)
        if response.table_query:
            modality_filters.append(RetrievalModality.TABLE)

        return QueryPlan(
            raw_query=query,
            normalized_query=normalized,
            query_intent=intent,
            page_filter=page_filter,
            modality_filters=tuple(modality_filters),
            title_like_phrases=response.title_phrases,
            quoted_phrases=response.quoted_phrases,
            structural_query=response.structural_query,
            visual_query=response.visual_query,
            table_query=response.table_query,
            requires_multimodal=response.visual_query,
        )

    def _fallback_plan(self, query: str, normalized: str) -> QueryPlan:
        """Keyword-based fallback when no gateway is available."""

        visual_terms = {"image", "photo", "figure", "diagram", "chart", "illustration"}
        table_terms = {"table", "tabular"}
        summary_terms = {"summarize", "summarise", "overview", "what is this document about"}
        structural_terms = {"section", "chapter", "appendix", "heading"}

        tokens = set(normalized.split())
        visual_query = bool(tokens & visual_terms)
        table_query = bool(tokens & table_terms)
        structural_query = bool(tokens & structural_terms)
        is_summary = any(term in normalized for term in summary_terms)

        if is_summary:
            intent = QueryIntent.DOCUMENT_SUMMARY
        elif visual_query:
            intent = QueryIntent.VISUAL_LOOKUP
        elif table_query:
            intent = QueryIntent.TABLE_LOOKUP
        elif structural_query:
            intent = QueryIntent.SECTION_LOOKUP
        else:
            intent = QueryIntent.TOPIC_LOOKUP

        modality_filters: list[RetrievalModality] = []
        if visual_query:
            modality_filters.append(RetrievalModality.VISUAL)
        if table_query:
            modality_filters.append(RetrievalModality.TABLE)

        return QueryPlan(
            raw_query=query,
            normalized_query=normalized,
            query_intent=intent,
            modality_filters=tuple(modality_filters),
            structural_query=structural_query,
            visual_query=visual_query,
            table_query=table_query,
            requires_multimodal=visual_query,
        )


__all__ = [
    "LLMQueryPlanner",
]
