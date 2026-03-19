"""Collection-scoped metadata selection before document retrieval."""

from __future__ import annotations

from typing import cast

from nullvector.domain.common import ScalarValue, is_numeric_scalar
from nullvector.domain.document_selection import (
    DocumentFilterClause,
    DocumentFilterOperator,
    DocumentMetadataRecord,
    DocumentSelectionCandidate,
    MetadataSelectionPlan,
    MetadataSelectionPlannerRequest,
    MetadataSelectionRequest,
    MetadataSelectionResponse,
)
from nullvector.llm.prompts.metadata_selection import (
    MetadataSelectionPromptResponse,
    build_metadata_selection_messages,
)
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest
from nullvector.retrieval._selection_artifacts import (
    selection_artifact_path,
    selection_artifact_root,
)
from nullvector.storage import StorageBackend, StorageConfig, build_document_store


def _record_sort_key(record: DocumentMetadataRecord) -> tuple[str, str]:
    return (record.display_name.casefold(), record.document_id)


def _validate_plan_fields(
    plan: MetadataSelectionPlan,
    *,
    allowed_fields: tuple[str, ...],
) -> None:
    allowed = set(allowed_fields)
    unknown_fields = tuple(
        sorted({clause.field for clause in plan.clauses if clause.field not in allowed})
    )
    if unknown_fields:
        msg = f"metadata selection plan references unknown fields: {unknown_fields}"
        raise ValueError(msg)


def _metadata_matches_clause(
    record: DocumentMetadataRecord,
    clause: DocumentFilterClause,
) -> bool:
    if clause.field not in record.attributes:
        return False
    actual = record.attributes[clause.field]
    if clause.operator is DocumentFilterOperator.EQ:
        return actual == clause.value
    if clause.operator is DocumentFilterOperator.IN:
        if not isinstance(clause.value, tuple):
            msg = "in filters require a tuple value"
            raise TypeError(msg)
        return actual in clause.value
    if clause.operator is DocumentFilterOperator.CONTAINS:
        return isinstance(actual, str) and cast(str, clause.value).casefold() in actual.casefold()
    if not is_numeric_scalar(actual):
        return False
    actual_numeric = cast(int | float, actual)
    expected = cast(int | float, clause.value)
    if clause.operator is DocumentFilterOperator.GTE:
        return float(actual_numeric) >= float(expected)
    return float(actual_numeric) <= float(expected)


def _matched_metadata(
    record: DocumentMetadataRecord,
    clauses: tuple[DocumentFilterClause, ...],
) -> dict[str, ScalarValue]:
    matched: dict[str, ScalarValue] = {}
    for clause in clauses:
        if clause.field in matched:
            continue
        if _metadata_matches_clause(record, clause):
            matched[clause.field] = record.attributes[clause.field]
    return matched


def _filter_in_memory(
    records: tuple[DocumentMetadataRecord, ...],
    *,
    clauses: tuple[DocumentFilterClause, ...],
    limit: int,
) -> tuple[DocumentMetadataRecord, ...]:
    ordered_records = tuple(sorted(records, key=_record_sort_key))
    matched = tuple(
        record
        for record in ordered_records
        if all(_metadata_matches_clause(record, clause) for clause in clauses)
    )
    return matched[:limit]


def _records_from_payloads(
    payloads: list[dict[str, object]],
) -> tuple[DocumentMetadataRecord, ...]:
    return tuple(
        DocumentMetadataRecord.model_validate(payload, strict=False) for payload in payloads
    )


def _candidate_from_record(
    record: DocumentMetadataRecord,
    *,
    clauses: tuple[DocumentFilterClause, ...],
) -> DocumentSelectionCandidate:
    matched_count = len(clauses)
    return DocumentSelectionCandidate(
        document_id=record.document_id,
        score=float(matched_count),
        selection_reason=f"matched {matched_count}/{matched_count} metadata clauses",
        matched_metadata=_matched_metadata(record, clauses),
    )


class MetadataSelectionPlanner:
    """Optional LLM-backed natural-language metadata selection planner."""

    def plan(
        self,
        request: MetadataSelectionPlannerRequest,
        *,
        gateway: StructuredLLMGateway,
    ) -> MetadataSelectionPlan:
        gateway_result = gateway.invoke(
            GatewayRequest[MetadataSelectionPromptResponse](
                operation_name="metadata_selection_plan",
                messages=build_metadata_selection_messages(
                    query=request.query,
                    allowed_fields=request.allowed_fields,
                    allowed_operators=request.allowed_operators,
                    field_descriptions=request.field_descriptions,
                ),
                response_model=MetadataSelectionPromptResponse,
                max_output_tokens=350,
                metadata={
                    "query": request.query,
                    "allowed_field_count": len(request.allowed_fields),
                },
            )
        )
        allowed_fields = set(request.allowed_fields)
        allowed_operators = set(request.allowed_operators)
        clauses = tuple(gateway_result.output.clauses)
        invalid_fields = tuple(
            sorted({clause.field for clause in clauses if clause.field not in allowed_fields})
        )
        if invalid_fields:
            msg = f"metadata_selection_plan returned unknown fields: {invalid_fields}"
            raise ValueError(msg)
        invalid_operators = tuple(
            sorted(
                {
                    clause.operator.value
                    for clause in clauses
                    if clause.operator not in allowed_operators
                }
            )
        )
        if invalid_operators:
            msg = f"metadata_selection_plan returned unsupported operators: {invalid_operators}"
            raise ValueError(msg)
        return MetadataSelectionPlan(
            raw_query=request.query,
            normalized_query=gateway_result.output.normalized_query,
            clauses=clauses,
            reasoning_summary=gateway_result.output.reasoning_summary,
        )


class MetadataSelectionService:
    """Execute typed metadata selection before document retrieval."""

    def __init__(self, *, storage: StorageConfig | None = None) -> None:
        self._storage = storage

    def select(self, request: MetadataSelectionRequest) -> MetadataSelectionResponse:
        _validate_plan_fields(request.plan, allowed_fields=request.allowed_fields)

        artifact_root = selection_artifact_root(
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            artifact_root=request.artifact_root,
            storage=self._storage,
        )
        store = build_document_store(self._storage, default_filesystem_root=".")

        if request.metadata_records:
            index_records = tuple(sorted(request.metadata_records, key=_record_sort_key))
            if store.backend is StorageBackend.POSTGRES:
                store.put_metadata_records(request.collection_id, index_records)
        elif store.backend is StorageBackend.POSTGRES:
            index_records = tuple(
                sorted(
                    _records_from_payloads(store.load_metadata_records(request.collection_id)),
                    key=_record_sort_key,
                )
            )
        else:
            msg = (
                "filesystem metadata selection requires metadata_records; "
                "loading persisted collection metadata is only supported for postgres storage"
            )
            raise ValueError(msg)

        metadata_index_path = store.put_jsonl_artifact(
            run_type="document_selection",
            run_id=request.selection_run_id,
            document_id=request.collection_id,
            artifact_kind="document_selection",
            artifact_path=selection_artifact_path(artifact_root, "metadata-index.jsonl"),
            payloads=tuple(record.model_dump(mode="json") for record in index_records),
        )
        selection_plan_path = store.put_json_artifact(
            run_type="document_selection",
            run_id=request.selection_run_id,
            document_id=request.collection_id,
            artifact_kind="document_selection",
            artifact_path=selection_artifact_path(
                artifact_root,
                "metadata-selection-plan.json",
            ),
            payload=request.plan,
        )

        if store.backend is StorageBackend.POSTGRES:
            matched_records = tuple(
                sorted(
                    _records_from_payloads(
                        store.query_metadata_records(
                            request.collection_id,
                            clauses=request.plan.clauses,
                            limit=request.limit,
                        )
                    ),
                    key=_record_sort_key,
                )
            )
        else:
            matched_records = _filter_in_memory(
                index_records,
                clauses=request.plan.clauses,
                limit=request.limit,
            )

        candidates = tuple(
            _candidate_from_record(record, clauses=request.plan.clauses)
            for record in matched_records
        )
        selection_results_path = store.put_json_artifact(
            run_type="document_selection",
            run_id=request.selection_run_id,
            document_id=request.collection_id,
            artifact_kind="document_selection",
            artifact_path=selection_artifact_path(
                artifact_root,
                "metadata-selection-results.json",
            ),
            payload={
                "collection_id": request.collection_id,
                "selection_run_id": request.selection_run_id,
                "candidate_count": len(candidates),
                "candidates": tuple(candidate.model_dump(mode="json") for candidate in candidates),
            },
        )
        return MetadataSelectionResponse(
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            candidates=candidates,
            artifact_root=artifact_root,
            metadata_index_path=metadata_index_path,
            selection_plan_path=selection_plan_path,
            selection_results_path=selection_results_path,
        )


__all__ = [
    "MetadataSelectionPlanner",
    "MetadataSelectionService",
]
