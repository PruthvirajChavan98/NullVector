"""LLM-driven retrieval ranker."""

from __future__ import annotations

from nullvector._text import normalize_text, tokenize
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalEvidence,
    RetrievalHit,
)
from nullvector.llm.prompts.retrieval_ranking import (
    RetrievalRankingResponse,
    build_retrieval_ranking_messages,
)
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest


class LLMRetrievalRanker:
    """LLM-driven retrieval ranker with keyword-overlap fallback."""

    def __init__(self, gateway: StructuredLLMGateway | None = None) -> None:
        self._gateway = gateway

    def rank(
        self,
        *,
        query: str,
        plan: QueryPlan,
        candidates: tuple[RetrievalEvidence, ...],
    ) -> tuple[RetrievalHit, ...]:
        """Rank candidates by relevance to the query."""

        if not candidates:
            return ()

        if self._gateway is not None:
            return self._llm_rank(query=query, plan=plan, candidates=candidates)
        return self._fallback_rank(query=query, plan=plan, candidates=candidates)

    def _llm_rank(
        self,
        *,
        query: str,
        plan: QueryPlan,
        candidates: tuple[RetrievalEvidence, ...],
    ) -> tuple[RetrievalHit, ...]:
        candidate_summaries = tuple(
            {
                "id": c.unit_id,
                "title": c.title or "",
                "text": (c.text or "")[:500],
            }
            for c in candidates
        )
        messages = build_retrieval_ranking_messages(
            query=query,
            candidate_summaries=candidate_summaries,
        )
        request: GatewayRequest[RetrievalRankingResponse] = GatewayRequest(
            operation_name="retrieval_ranking",
            messages=messages,
            response_model=RetrievalRankingResponse,
            temperature=0.0,
        )
        result = self._gateway.invoke(request)  # type: ignore[union-attr]
        response = result.output

        score_by_id: dict[str, float] = {}
        for uid, score in zip(response.ranked_ids, response.scores, strict=False):
            score_by_id[uid] = score

        hits: list[RetrievalHit] = []
        for candidate in candidates:
            score = score_by_id.get(candidate.unit_id, 0.0)
            hits.append(
                RetrievalHit(
                    unit=candidate,
                    score=score,
                    score_breakdown={"llm_relevance": score},
                )
            )

        return tuple(sorted(hits, key=lambda h: h.score, reverse=True))

    def _fallback_rank(
        self,
        *,
        query: str,
        plan: QueryPlan,
        candidates: tuple[RetrievalEvidence, ...],
    ) -> tuple[RetrievalHit, ...]:
        """Simple keyword overlap ranking when no gateway is available."""

        query_tokens = set(tokenize(normalize_text(query)))
        hits: list[RetrievalHit] = []

        for candidate in candidates:
            candidate_text = f"{candidate.title or ''} {candidate.text or ''}"
            candidate_tokens = set(tokenize(normalize_text(candidate_text)))
            overlap = query_tokens & candidate_tokens
            score = len(overlap) * 2.0

            hits.append(
                RetrievalHit(
                    unit=candidate,
                    score=score,
                    score_breakdown={"keyword_overlap": score},
                    matched_terms=tuple(sorted(overlap)),
                )
            )

        return tuple(sorted(hits, key=lambda h: h.score, reverse=True))


__all__ = [
    "LLMRetrievalRanker",
]
