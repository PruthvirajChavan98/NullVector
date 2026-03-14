"""Deterministic query planning for retrieval."""

from __future__ import annotations

import re
import string

from nullvector.domain.models import PageSpan
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalModality,
    RetrievalUnitType,
)

_QUOTED_PATTERN = re.compile(r"['\"]([^'\"]+)['\"]")
_PAGE_NUMBER_PATTERN = re.compile(r"\bpage\s+(?P<number>\d+)\b")
_STRUCTURAL_PATTERN = re.compile(r"\b(?:section|chapter|appendix|heading)\s+[a-z0-9][a-z0-9 .:-]*")
_PUNCTUATION_TABLE = str.maketrans({character: " " for character in string.punctuation})
_VISUAL_TERMS = ("image", "photo", "figure", "diagram", "chart", "illustration")
_TABLE_TERMS = ("table", "tabular")


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split()).strip()


def _normalize_phrase(value: str) -> str:
    return _collapse_whitespace(value.casefold().translate(_PUNCTUATION_TABLE))


def _dedupe(values: list[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _collapse_whitespace(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def _quoted_phrases(query: str) -> tuple[str, ...]:
    return _dedupe([_normalize_phrase(match.group(1)) for match in _QUOTED_PATTERN.finditer(query)])


def _page_filter(normalized_query: str) -> PageSpan | None:
    if "first page" in normalized_query:
        return PageSpan(start_page=0, end_page=0)

    page_match = _PAGE_NUMBER_PATTERN.search(normalized_query)
    if page_match is None:
        return None

    page_number = int(page_match.group("number"))
    page_index = 0 if page_number <= 1 else page_number - 1
    return PageSpan(start_page=page_index, end_page=page_index)


def _title_like_phrases(
    *,
    normalized_query: str,
    quoted_phrases: tuple[str, ...],
) -> tuple[str, ...]:
    phrases = list(quoted_phrases)
    phrases.extend(
        _normalize_phrase(match.group(0))
        for match in _STRUCTURAL_PATTERN.finditer(normalized_query)
    )
    return _dedupe(phrases)


class QueryPlanner:
    """Deterministic planner that extracts page, modality, and structural intent."""

    def plan(self, query: str) -> QueryPlan:
        normalized_query = _normalize_phrase(query)
        quoted_phrases = _quoted_phrases(query)
        title_like_phrases = _title_like_phrases(
            normalized_query=normalized_query,
            quoted_phrases=quoted_phrases,
        )
        visual_query = any(term in normalized_query.split() for term in _VISUAL_TERMS)
        table_query = any(term in normalized_query.split() for term in _TABLE_TERMS)
        structural_query = bool(
            title_like_phrases
            or quoted_phrases
            or any(
                term in normalized_query
                for term in ("section", "chapter", "appendix", "heading")
            )
        )

        unit_types: tuple[RetrievalUnitType, ...] = ()
        modality_filters: tuple[RetrievalModality, ...] = ()
        if visual_query:
            unit_types = (
                RetrievalUnitType.VISUAL,
                RetrievalUnitType.UNRESOLVED_VISUAL,
            )
            modality_filters = (RetrievalModality.VISUAL,)
        elif table_query:
            unit_types = (RetrievalUnitType.TABLE,)
            modality_filters = (RetrievalModality.TABLE,)
        elif structural_query:
            unit_types = (
                RetrievalUnitType.NODE_TEXT,
                RetrievalUnitType.NODE_SUMMARY,
                RetrievalUnitType.UNASSIGNED_SPAN,
                RetrievalUnitType.PAGE_TEXT,
            )

        return QueryPlan(
            raw_query=query,
            normalized_query=normalized_query,
            page_filter=_page_filter(normalized_query),
            unit_types=unit_types,
            modality_filters=modality_filters,
            title_like_phrases=title_like_phrases,
            quoted_phrases=quoted_phrases,
            structural_query=structural_query,
            visual_query=visual_query,
            table_query=table_query,
            requires_multimodal=visual_query,
        )


__all__ = ["QueryPlanner"]
