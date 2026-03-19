"""Metadata-selection planner and service tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from nullvector.domain.common import ScalarValue, is_numeric_scalar
from nullvector.domain.document_selection import (
    DocumentFilterClause,
    DocumentFilterOperator,
    DocumentMetadataRecord,
    MetadataSelectionPlan,
    MetadataSelectionPlannerRequest,
    MetadataSelectionRequest,
)
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.llm.types import JSONValue
from nullvector.retrieval import MetadataSelectionPlanner, MetadataSelectionService
from nullvector.storage import (
    FilesystemStorageConfig,
    PostgresStorageConfig,
    StorageBackend,
    build_postgres_artifact_ref,
)


def _record(
    *,
    document_id: str,
    display_name: str,
    **attributes: ScalarValue,
) -> DocumentMetadataRecord:
    return DocumentMetadataRecord(
        document_id=document_id,
        display_name=display_name,
        attributes=attributes,
    )


def _planner_gateway(
    tmp_path: Path,
    *,
    output_json: dict[str, JSONValue],
) -> GatewayService:
    return GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "metadata_selection_plan": NoopScriptedResponse(output_json=output_json),
            }
        ),
    )


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            {"field": "company", "operator": "contains", "value": 2024},
            "contains filters require a string value",
        ),
        (
            {"field": "year", "operator": "gte", "value": "2024"},
            "gte filters require a numeric value",
        ),
        (
            {"field": "company", "operator": "in", "value": "Acme"},
            "in filters require a non-empty tuple",
        ),
        (
            {"field": "company", "operator": "eq", "value": ["Acme", "Beta"]},
            "eq filters require one scalar value",
        ),
    ],
)
def test_document_filter_clause_validates_value_shape(
    payload: dict[str, object],
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        DocumentFilterClause.model_validate(payload)


def test_selection_service_filters_and_persists_in_memory_artifacts(tmp_path: Path) -> None:
    service = MetadataSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )
    records = (
        _record(
            document_id="doc-001",
            display_name="Acme Annual Report 2024",
            company="Acme",
            year=2024,
            case_type="report",
        ),
        _record(
            document_id="doc-002",
            display_name="Acme Board Memo 2022",
            company="Acme",
            year=2022,
            case_type="memo",
        ),
        _record(
            document_id="doc-003",
            display_name="Beta Litigation 2024",
            company="Beta",
            year=2024,
            case_type="litigation",
        ),
    )
    plan = MetadataSelectionPlan(
        raw_query="Acme 2024 report",
        normalized_query="acme 2024 report",
        clauses=(
            DocumentFilterClause(
                field="company",
                operator=DocumentFilterOperator.EQ,
                value="Acme",
            ),
            DocumentFilterClause(
                field="year",
                operator=DocumentFilterOperator.GTE,
                value=2023,
            ),
        ),
        reasoning_summary="Prefer Acme documents published in or after 2023.",
    )

    response = service.select(
        MetadataSelectionRequest(
            collection_id="collection-alpha",
            selection_run_id="selection-001",
            plan=plan,
            allowed_fields=("company", "year", "case_type"),
            metadata_records=records,
            limit=5,
        )
    )

    assert tuple(candidate.document_id for candidate in response.candidates) == ("doc-001",)
    assert response.candidates[0].matched_metadata == {"company": "Acme", "year": 2024}

    index_payload = Path(response.metadata_index_path).read_text(encoding="utf-8").splitlines()
    plan_payload = json.loads(Path(response.selection_plan_path).read_text(encoding="utf-8"))
    results_payload = json.loads(Path(response.selection_results_path).read_text(encoding="utf-8"))

    assert len(index_payload) == 3
    assert plan_payload["normalized_query"] == "acme 2024 report"
    assert results_payload["candidates"][0]["document_id"] == "doc-001"


def test_selection_service_orders_candidates_deterministically(tmp_path: Path) -> None:
    service = MetadataSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )
    records = (
        _record(document_id="doc-b", display_name="alpha brief", company="Acme"),
        _record(document_id="doc-a", display_name="Alpha Brief", company="Acme"),
        _record(document_id="doc-c", display_name="Zulu Brief", company="Acme"),
    )
    plan = MetadataSelectionPlan(
        raw_query="all acme docs",
        normalized_query="all acme docs",
        clauses=(
            DocumentFilterClause(
                field="company",
                operator=DocumentFilterOperator.EQ,
                value="Acme",
            ),
        ),
    )

    response = service.select(
        MetadataSelectionRequest(
            collection_id="collection-ordering",
            selection_run_id="selection-002",
            plan=plan,
            allowed_fields=("company",),
            metadata_records=records,
            limit=3,
        )
    )

    assert tuple(candidate.document_id for candidate in response.candidates) == (
        "doc-a",
        "doc-b",
        "doc-c",
    )


def test_selection_service_returns_empty_candidates_when_nothing_matches(tmp_path: Path) -> None:
    service = MetadataSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )
    plan = MetadataSelectionPlan(
        raw_query="Gamma matters",
        normalized_query="gamma matters",
        clauses=(
            DocumentFilterClause(
                field="company",
                operator=DocumentFilterOperator.EQ,
                value="Gamma",
            ),
        ),
    )

    response = service.select(
        MetadataSelectionRequest(
            collection_id="collection-empty",
            selection_run_id="selection-003",
            plan=plan,
            allowed_fields=("company",),
            metadata_records=(
                _record(document_id="doc-001", display_name="Acme File", company="Acme"),
            ),
        )
    )

    assert response.candidates == ()


def test_selection_service_requires_metadata_records_for_filesystem_storage(
    tmp_path: Path,
) -> None:
    service = MetadataSelectionService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    )

    with pytest.raises(ValueError, match="filesystem metadata selection requires metadata_records"):
        service.select(
            MetadataSelectionRequest(
                collection_id="collection-missing",
                selection_run_id="selection-004",
                plan=MetadataSelectionPlan(
                    raw_query="Acme",
                    normalized_query="acme",
                ),
                allowed_fields=("company",),
            )
        )


def test_planner_builds_validated_plan_from_gateway(tmp_path: Path) -> None:
    gateway = _planner_gateway(
        tmp_path,
        output_json={
            "normalized_query": "acme 2024 report",
            "clauses": [
                {"field": "company", "operator": "eq", "value": "Acme"},
                {"field": "year", "operator": "eq", "value": 2024},
            ],
            "reasoning_summary": "Use company and publication year.",
        },
    )

    plan = MetadataSelectionPlanner().plan(
        MetadataSelectionPlannerRequest(
            query="Acme 2024 report",
            allowed_fields=("company", "year"),
            field_descriptions={"company": "Issuer name", "year": "Publication year"},
        ),
        gateway=gateway,
    )

    assert plan.normalized_query == "acme 2024 report"
    assert tuple(clause.field for clause in plan.clauses) == ("company", "year")


def test_planner_rejects_unknown_fields_from_gateway(tmp_path: Path) -> None:
    gateway = _planner_gateway(
        tmp_path,
        output_json={
            "normalized_query": "acme 2024 report",
            "clauses": [
                {"field": "unknown_field", "operator": "eq", "value": "Acme"},
            ],
        },
    )

    with pytest.raises(ValueError, match="unknown fields"):
        MetadataSelectionPlanner().plan(
            MetadataSelectionPlannerRequest(
                query="Acme 2024 report",
                allowed_fields=("company", "year"),
            ),
            gateway=gateway,
        )


class _FakePostgresStore:
    backend = StorageBackend.POSTGRES

    def __init__(self) -> None:
        self.persisted: tuple[DocumentMetadataRecord, ...] = ()
        self.upsert_calls: list[tuple[str, tuple[DocumentMetadataRecord, ...]]] = []
        self.query_calls: list[dict[str, object]] = []

    def put_metadata_records(
        self,
        collection_id: str,
        records: tuple[DocumentMetadataRecord, ...],
    ) -> int:
        self.persisted = records
        self.upsert_calls.append((collection_id, records))
        return len(records)

    def load_metadata_records(self, collection_id: str) -> list[dict[str, object]]:
        del collection_id
        return [record.model_dump(mode="json") for record in self.persisted]

    def query_metadata_records(
        self,
        collection_id: str,
        *,
        clauses: tuple[DocumentFilterClause, ...] = (),
        limit: int = 50,
    ) -> list[dict[str, object]]:
        self.query_calls.append(
            {
                "collection_id": collection_id,
                "clauses": clauses,
                "limit": limit,
            }
        )

        def matches(record: DocumentMetadataRecord) -> bool:
            for clause in clauses:
                value = record.attributes.get(clause.field)
                if clause.operator is DocumentFilterOperator.EQ and value != clause.value:
                    return False
                if clause.operator is DocumentFilterOperator.GTE:
                    if value is None:
                        return False
                    if not is_numeric_scalar(value) or not is_numeric_scalar(clause.value):
                        return False
                    if cast(int | float, value) < cast(int | float, clause.value):
                        return False
            return True

        return [
            record.model_dump(mode="json")
            for record in sorted(
                self.persisted,
                key=lambda item: (item.display_name.casefold(), item.document_id),
            )
            if matches(record)
        ][:limit]

    def put_json_artifact(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_kind: str,
        artifact_path: str,
        payload: object,
    ) -> str:
        del artifact_kind, payload
        return build_postgres_artifact_ref(
            run_type=run_type,
            run_id=run_id,
            document_id=document_id,
            artifact_path=artifact_path,
        )

    def put_jsonl_artifact(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_kind: str,
        artifact_path: str,
        payloads: tuple[object, ...],
    ) -> str:
        del artifact_kind, payloads
        return build_postgres_artifact_ref(
            run_type=run_type,
            run_id=run_id,
            document_id=document_id,
            artifact_path=artifact_path,
        )


def test_selection_service_uses_postgres_metadata_store_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_store = _FakePostgresStore()
    monkeypatch.setattr(
        "nullvector.retrieval.metadata_selection.build_document_store",
        lambda storage, default_filesystem_root=None: fake_store,
    )
    service = MetadataSelectionService(
        storage=PostgresStorageConfig(conninfo="postgresql://example/nullvector")
    )
    records = (
        _record(document_id="doc-001", display_name="Acme File", company="Acme", year=2024),
        _record(document_id="doc-002", display_name="Beta File", company="Beta", year=2024),
    )
    plan = MetadataSelectionPlan(
        raw_query="Acme 2024",
        normalized_query="acme 2024",
        clauses=(
            DocumentFilterClause(
                field="company",
                operator=DocumentFilterOperator.EQ,
                value="Acme",
            ),
            DocumentFilterClause(
                field="year",
                operator=DocumentFilterOperator.GTE,
                value=2024,
            ),
        ),
    )

    response = service.select(
        MetadataSelectionRequest(
            collection_id="collection-postgres",
            selection_run_id="selection-005",
            plan=plan,
            allowed_fields=("company", "year"),
            metadata_records=records,
            limit=5,
        )
    )

    assert tuple(candidate.document_id for candidate in response.candidates) == ("doc-001",)
    assert fake_store.upsert_calls[0][0] == "collection-postgres"
    assert fake_store.query_calls[0]["limit"] == 5
    assert response.metadata_index_path.startswith("pg://document_selection/")
