"""Vectorless in-memory retrieval index."""

from __future__ import annotations

import string
from collections import defaultdict

from nullvector.domain.models import PageSpan
from nullvector.domain.retrieval import QueryPlan, RetrievalCorpus, RetrievalEvidence

_PUNCTUATION_TABLE = str.maketrans({character: " " for character in string.punctuation})


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().translate(_PUNCTUATION_TABLE).split())


def _tokenize(value: str) -> tuple[str, ...]:
    normalized = _normalize_text(value)
    return tuple(token for token in normalized.split() if token)


def _intersects(left: PageSpan, right: PageSpan) -> bool:
    return not (left.end_page < right.start_page or right.end_page < left.start_page)


class InMemoryRetrievalIndex:
    """Simple postings-based index over one retrieval corpus."""

    def __init__(self, corpus: RetrievalCorpus) -> None:
        self._corpus = corpus
        self._token_postings: dict[str, tuple[str, ...]] = {}
        self._title_postings: dict[str, tuple[str, ...]] = {}
        self._keyword_postings: dict[str, tuple[str, ...]] = {}
        self._page_number_lookup: dict[int, tuple[str, ...]] = {}
        self._node_id_lookup: dict[str, tuple[str, ...]] = {}
        self._units_by_id = {unit.unit_id: unit for unit in corpus.units}
        self._build_indexes()

    @property
    def corpus(self) -> RetrievalCorpus:
        return self._corpus

    def filter_units(self, plan: QueryPlan) -> tuple[RetrievalEvidence, ...]:
        candidates = self._corpus.units
        if plan.page_filter is not None:
            page_filter = plan.page_filter
            candidates = tuple(
                unit
                for unit in candidates
                if _intersects(unit.page_span, page_filter)
            )
        if plan.unit_types:
            allowed_types = set(plan.unit_types)
            candidates = tuple(unit for unit in candidates if unit.unit_type in allowed_types)
        if plan.modality_filters:
            allowed_modalities = set(plan.modality_filters)
            candidates = tuple(unit for unit in candidates if unit.modality in allowed_modalities)
        return candidates

    def postings(self, token: str) -> tuple[str, ...]:
        return self._token_postings.get(_normalize_text(token), ())

    def _build_indexes(self) -> None:
        token_postings: dict[str, set[str]] = defaultdict(set)
        title_postings: dict[str, set[str]] = defaultdict(set)
        keyword_postings: dict[str, set[str]] = defaultdict(set)
        page_number_lookup: dict[int, set[str]] = defaultdict(set)
        node_id_lookup: dict[str, set[str]] = defaultdict(set)

        for unit in self._corpus.units:
            for page_index in range(unit.page_span.start_page, unit.page_span.end_page + 1):
                page_number_lookup[page_index].add(unit.unit_id)
            if unit.node_id is not None:
                node_id_lookup[unit.node_id].add(unit.unit_id)

            token_source = " ".join(
                part
                for part in (unit.title or "", unit.text or "", " ".join(unit.keywords))
                if part
            )
            for token in _tokenize(token_source):
                token_postings[token].add(unit.unit_id)
            if unit.title is not None:
                for token in _tokenize(unit.title):
                    title_postings[token].add(unit.unit_id)
            for keyword in unit.keywords:
                for token in _tokenize(keyword):
                    keyword_postings[token].add(unit.unit_id)

        self._token_postings = {
            token: tuple(sorted(unit_ids)) for token, unit_ids in token_postings.items()
        }
        self._title_postings = {
            token: tuple(sorted(unit_ids)) for token, unit_ids in title_postings.items()
        }
        self._keyword_postings = {
            token: tuple(sorted(unit_ids)) for token, unit_ids in keyword_postings.items()
        }
        self._page_number_lookup = {
            page_index: tuple(sorted(unit_ids))
            for page_index, unit_ids in page_number_lookup.items()
        }
        self._node_id_lookup = {
            node_id: tuple(sorted(unit_ids)) for node_id, unit_ids in node_id_lookup.items()
        }


__all__ = ["InMemoryRetrievalIndex"]
