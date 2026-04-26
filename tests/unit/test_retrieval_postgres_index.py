"""Unit coverage for the PostgreSQL-backed retrieval index shim."""

from __future__ import annotations

from typing import Any

from nullvector.domain.common import ContentSpan, PageSpan
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalCorpus,
    RetrievalEvidence,
    RetrievalModality,
    RetrievalUnitType,
)
from nullvector.retrieval.index import InMemoryRetrievalIndex, PostgresRetrievalIndex


class _FakeStore:
    def __init__(self, payloads: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payloads = payloads

    def query_retrieval_units(
        self,
        document_id: str,
        *,
        page_start: int | None = None,
        page_end: int | None = None,
        unit_types: tuple[str, ...] = (),
        modalities: tuple[str, ...] = (),
        text_query: str | None = None,
        limit: int | None = 50,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "document_id": document_id,
                "page_start": page_start,
                "page_end": page_end,
                "unit_types": unit_types,
                "modalities": modalities,
                "text_query": text_query,
                "limit": limit,
            }
        )
        if self._payloads is not None:
            rows = list(self._payloads)
            rows.sort(
                key=lambda row: (
                    row["page_span"]["start_page"],
                    row["page_span"]["end_page"],
                    str(row.get("title") or "").lower(),
                    row["unit_id"],
                )
            )
            return rows
        return [
            RetrievalEvidence(
                unit_id="unit-1",
                document_id=document_id,
                unit_type=RetrievalUnitType.NODE_TEXT,
                modality=RetrievalModality.TEXT,
                page_span=PageSpan(start_page=1, end_page=2),
                content_span=ContentSpan(
                    start_page=1,
                    start_offset=0,
                    end_page=2,
                    end_offset=12,
                ),
                title="Overview",
                text="hello world",
            ).model_dump(mode="json")
        ]


def test_postgres_index_translates_plan_filters_to_store_query() -> None:
    store = _FakeStore()
    index = PostgresRetrievalIndex(store, document_id="doc-001")  # type: ignore[arg-type]
    plan = QueryPlan(
        raw_query="overview",
        normalized_query="overview",
        page_filter=PageSpan(start_page=1, end_page=3),
        unit_types=(RetrievalUnitType.NODE_TEXT,),
        modality_filters=(RetrievalModality.TEXT,),
    )

    results = index.filter_units(plan)

    assert len(results) == 1
    assert results[0].unit_id == "unit-1"
    assert store.calls == [
        {
            "document_id": "doc-001",
            "page_start": 1,
            "page_end": 3,
            "unit_types": ("node_text",),
            "modalities": ("text",),
            "text_query": None,
            "limit": None,
        }
    ]


def test_in_memory_and_postgres_indexes_return_equivalent_filtered_candidates() -> None:
    corpus = RetrievalCorpus(
        document_id="doc-001",
        units=(
            RetrievalEvidence(
                unit_id="unit-2",
                document_id="doc-001",
                unit_type=RetrievalUnitType.NODE_TEXT,
                modality=RetrievalModality.TEXT,
                page_span=PageSpan(start_page=2, end_page=2),
                content_span=ContentSpan(
                    start_page=2,
                    start_offset=0,
                    end_page=2,
                    end_offset=8,
                ),
                title="Zulu",
                text="two",
            ),
            RetrievalEvidence(
                unit_id="unit-1",
                document_id="doc-001",
                unit_type=RetrievalUnitType.NODE_TEXT,
                modality=RetrievalModality.TEXT,
                page_span=PageSpan(start_page=1, end_page=2),
                content_span=ContentSpan(
                    start_page=1,
                    start_offset=0,
                    end_page=2,
                    end_offset=12,
                ),
                title="Overview",
                text="hello world",
            ),
        ),
    )
    store = _FakeStore([unit.model_dump(mode="json") for unit in corpus.units])
    postgres_index = PostgresRetrievalIndex(store, document_id="doc-001")  # type: ignore[arg-type]
    in_memory_index = InMemoryRetrievalIndex(corpus)
    plan = QueryPlan(
        raw_query="overview",
        normalized_query="overview",
        page_filter=PageSpan(start_page=1, end_page=3),
        unit_types=(RetrievalUnitType.NODE_TEXT,),
        modality_filters=(RetrievalModality.TEXT,),
    )

    in_memory_results = in_memory_index.filter_units(plan)
    postgres_results = postgres_index.filter_units(plan)

    assert [unit.unit_id for unit in in_memory_results] == [
        unit.unit_id for unit in postgres_results
    ]
