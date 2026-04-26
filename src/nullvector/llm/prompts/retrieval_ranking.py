"""Prompt builder for LLM-driven retrieval ranking."""

from __future__ import annotations

import json

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.llm.types import LLMMessage, LLMRole


class RetrievalRankingResponse(NullVectorModel):
    """Typed structured response for LLM retrieval ranking."""

    ranked_ids: tuple[NonEmptyStr, ...] = ()
    scores: tuple[float, ...] = ()


def build_retrieval_ranking_messages(
    *,
    query: str,
    candidate_summaries: tuple[dict[str, str], ...],
) -> tuple[LLMMessage, ...]:
    """Build prompt messages for LLM retrieval ranking."""

    payload = json.dumps(
        {"query": query, "candidates": list(candidate_summaries)},
        indent=2,
        ensure_ascii=True,
    )
    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are a document retrieval relevance ranker. "
                "Given a user query and a list of candidate text segments, "
                "rank the candidates by relevance to the query. "
                "Return a JSON object with fields: "
                "ranked_ids (array of candidate IDs ordered by relevance, most relevant first), "
                "scores (array of relevance scores 0.0-1.0, same order as ranked_ids)."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=f"Rank these candidates by relevance:\n{payload}",
        ),
    )


__all__ = [
    "RetrievalRankingResponse",
    "build_retrieval_ranking_messages",
]
