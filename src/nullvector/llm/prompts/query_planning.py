"""Prompt builder for LLM-driven query planning."""

from __future__ import annotations

import json

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.llm.types import LLMMessage, LLMRole


class QueryPlanningResponse(NullVectorModel):
    """Typed structured response for LLM query planning."""

    intent: NonEmptyStr = "topic_lookup"
    page_filter_start: int | None = None
    page_filter_end: int | None = None
    structural_query: bool = False
    visual_query: bool = False
    table_query: bool = False
    title_phrases: tuple[NonEmptyStr, ...] = ()
    quoted_phrases: tuple[NonEmptyStr, ...] = ()


def build_query_planning_messages(query: str) -> tuple[LLMMessage, ...]:
    """Build prompt messages for LLM query planning."""

    payload = json.dumps({"query": query}, indent=2, ensure_ascii=True)
    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are a document retrieval query analyzer. "
                "Classify the user's query intent and extract structured routing signals. "
                "Return a JSON object with fields: "
                "intent (one of: topic_lookup, document_summary, visual_lookup, "
                "table_lookup, page_lookup, quote_lookup, section_lookup), "
                "page_filter_start (0-indexed page number or null), "
                "page_filter_end (0-indexed page number or null), "
                "structural_query (boolean — section/chapter/heading references), "
                "visual_query (boolean — image/figure/diagram references), "
                "table_query (boolean — table/tabular references), "
                "title_phrases (array of key phrases or section titles from the query), "
                "quoted_phrases (array of exact-quoted text from the query)."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=f"Analyze this retrieval query:\n{payload}",
        ),
    )


__all__ = [
    "QueryPlanningResponse",
    "build_query_planning_messages",
]
