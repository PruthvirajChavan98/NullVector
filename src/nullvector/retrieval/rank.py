"""Deterministic ranking for retrieval candidates."""

from __future__ import annotations

from nullvector._text import normalize_text, tokenize
from nullvector.domain.common import PageSpan
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalEvidence,
    RetrievalHit,
    RetrievalUnitType,
)

_STOPWORDS = {
    "a",
    "about",
    "an",
    "the",
    "is",
    "of",
    "on",
    "what",
    "which",
    "who",
    "where",
    "when",
    "why",
}
_STOPWORDS_FROZEN = frozenset(_STOPWORDS)


def _intersects(left: PageSpan, right: PageSpan) -> bool:
    return not (left.end_page < right.start_page or right.end_page < left.start_page)


def _contains_phrase(candidate: RetrievalEvidence, phrase: str) -> bool:
    haystacks = [candidate.title or "", candidate.text or ""]
    normalized_phrase = normalize_text(phrase)
    return any(normalized_phrase in normalize_text(value) for value in haystacks if value)


def _matched_terms(
    *,
    query_tokens: tuple[str, ...],
    candidate: RetrievalEvidence,
    quoted_phrases: tuple[str, ...],
) -> tuple[str, ...]:
    terms: list[str] = []
    candidate_tokens = set(
        tokenize(
            " ".join(part for part in (candidate.title or "", candidate.text or "") if part),
            stopwords=_STOPWORDS_FROZEN,
        )
    )
    for token in query_tokens:
        if token in candidate_tokens and token not in terms:
            terms.append(token)
    for phrase in quoted_phrases:
        if _contains_phrase(candidate, phrase) and phrase not in terms:
            terms.append(phrase)
    return tuple(terms)


class RetrievalRanker:
    """Deterministic scorer over already-filtered retrieval evidence."""

    def rank(
        self,
        *,
        query: str,
        plan: QueryPlan,
        candidates: tuple[RetrievalEvidence, ...],
    ) -> tuple[RetrievalHit, ...]:
        query_tokens = tokenize(query, stopwords=_STOPWORDS_FROZEN)
        hits: list[RetrievalHit] = []

        for candidate in candidates:
            breakdown: dict[str, float] = {}

            if plan.page_filter is not None:
                if candidate.page_span == plan.page_filter:
                    breakdown["page_exact"] = 12.0
                elif _intersects(candidate.page_span, plan.page_filter):
                    breakdown["page_overlap"] = 6.0
                else:
                    breakdown["page_miss_penalty"] = -12.0

            if plan.modality_filters:
                if candidate.modality in set(plan.modality_filters):
                    breakdown["modality_match"] = 10.0
                else:
                    breakdown["modality_mismatch_penalty"] = -10.0

            if plan.visual_query:
                if candidate.unit_type in {
                    RetrievalUnitType.VISUAL,
                    RetrievalUnitType.UNRESOLVED_VISUAL,
                }:
                    breakdown["visual_intent_match"] = 8.0
                else:
                    breakdown["visual_intent_penalty"] = -14.0

            if plan.table_query:
                if candidate.unit_type is RetrievalUnitType.TABLE:
                    breakdown["table_intent_match"] = 8.0
                else:
                    breakdown["table_intent_penalty"] = -8.0

            quoted_matches = sum(
                1 for phrase in plan.quoted_phrases if _contains_phrase(candidate, phrase)
            )
            if quoted_matches:
                breakdown["quoted_phrase_match"] = 12.0 * quoted_matches

            title_matches = 0.0
            normalized_title = normalize_text(candidate.title or "")
            for phrase in plan.title_like_phrases:
                normalized_phrase = normalize_text(phrase)
                if normalized_phrase and normalized_phrase == normalized_title:
                    title_matches += 1
                elif normalized_phrase and normalized_phrase in normalized_title:
                    title_matches += 0.5
            if title_matches:
                breakdown["title_match"] = 8.0 * title_matches

            keyword_overlap = len(
                set(query_tokens)
                & set(tokenize(" ".join(candidate.keywords), stopwords=_STOPWORDS_FROZEN))
            )
            if keyword_overlap:
                breakdown["keyword_overlap"] = 2.0 * keyword_overlap

            token_overlap = len(
                set(query_tokens)
                & set(
                    tokenize(
                        " ".join(
                            part for part in (candidate.title or "", candidate.text or "") if part
                        ),
                        stopwords=_STOPWORDS_FROZEN,
                    )
                )
            )
            if token_overlap:
                breakdown["token_overlap"] = 1.5 * token_overlap

            matched_query_signal = any(
                value > 0.0
                for key, value in breakdown.items()
                if key
                in {
                    "page_exact",
                    "page_overlap",
                    "modality_match",
                    "visual_intent_match",
                    "table_intent_match",
                    "quoted_phrase_match",
                    "title_match",
                    "keyword_overlap",
                    "token_overlap",
                }
            )

            if candidate.authoritative and matched_query_signal:
                breakdown["authoritative_bonus"] = 2.0
            if (
                candidate.unit_type is RetrievalUnitType.NODE_TEXT
                and candidate.metadata.get("verified") is True
                and matched_query_signal
            ):
                breakdown["verified_node_bonus"] = 1.5
            if candidate.unit_type is RetrievalUnitType.NODE_SUMMARY and matched_query_signal:
                breakdown["summary_penalty"] = -2.5
            if candidate.interpretive and not plan.visual_query and matched_query_signal:
                breakdown["interpretive_penalty"] = -5.0
            if candidate.unit_type is RetrievalUnitType.UNRESOLVED_VISUAL and not candidate.text:
                breakdown["unresolved_visual_penalty"] = -3.0
            if candidate.text in (None, "") and candidate.unit_type not in {
                RetrievalUnitType.VISUAL,
                RetrievalUnitType.UNRESOLVED_VISUAL,
            }:
                breakdown["empty_text_penalty"] = -4.0

            score = sum(breakdown.values())
            hits.append(
                RetrievalHit(
                    unit=candidate,
                    score=score,
                    score_breakdown=breakdown,
                    matched_terms=_matched_terms(
                        query_tokens=query_tokens,
                        candidate=candidate,
                        quoted_phrases=plan.quoted_phrases,
                    ),
                )
            )

        return tuple(
            sorted(
                hits,
                key=lambda hit: (
                    hit.score,
                    hit.unit.authoritative,
                    hit.unit.unit_type.value,
                    hit.unit.unit_id,
                ),
                reverse=True,
            )
        )


__all__ = ["RetrievalRanker"]
