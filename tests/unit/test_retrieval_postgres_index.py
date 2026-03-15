"""Unit coverage for the PostgreSQL-backed retrieval index shim."""

from __future__ import annotations

from typing import Any

from nullvector.domain.common import ContentSpan, PageSpan
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalEvidence,
    RetrievalModality,
    RetrievalUnitType,
)
from nullvector.retrieval.index import PostgresRetrievalIndex


class _FakeStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def query_retrieval_units(
        self,
        document_id: str,
        *,
        page_start: int | None = None,
        page_end: int | None = None,
        unit_types: tuple[str, ...] = (),
        modalities: tuple[str, ...] = (),
        text_query: str | None = None,
        limit: int = 50,
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
            "text_query": "overview",
            "limit": 250,
        }
    ]
