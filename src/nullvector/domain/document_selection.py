"""Collection-level metadata selection contracts for retrieval routing."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import Field, NonNegativeFloat, PositiveInt, model_validator

from nullvector.domain.common import NonEmptyStr, NullVectorModel, ScalarValue, is_numeric_scalar


class DocumentFilterOperator(StrEnum):
    """Supported typed metadata-filter operators."""

    EQ = "eq"
    IN = "in"
    CONTAINS = "contains"
    GTE = "gte"
    LTE = "lte"


class DocumentMetadataRecord(NullVectorModel):
    """One collection-scoped document metadata record."""

    document_id: NonEmptyStr
    display_name: NonEmptyStr
    attributes: dict[str, ScalarValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_attributes(self) -> Self:
        for key in self.attributes:
            if not key.strip():
                msg = "metadata attribute keys must be non-empty"
                raise ValueError(msg)
        return self


class DocumentFilterClause(NullVectorModel):
    """One typed metadata filter clause."""

    field: NonEmptyStr
    operator: DocumentFilterOperator
    value: ScalarValue | tuple[ScalarValue, ...]

    @model_validator(mode="before")
    @classmethod
    def coerce_sequence_values(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        operator = data.get("operator")
        if isinstance(operator, str):
            data = {**data, "operator": DocumentFilterOperator(operator)}
        value = data.get("value")
        if isinstance(value, list):
            return {**data, "value": tuple(value)}
        return data

    @model_validator(mode="after")
    def validate_value_for_operator(self) -> Self:
        if self.operator is DocumentFilterOperator.EQ:
            if isinstance(self.value, tuple):
                msg = "eq filters require one scalar value"
                raise ValueError(msg)
            return self
        if self.operator is DocumentFilterOperator.IN:
            if not isinstance(self.value, tuple) or not self.value:
                msg = "in filters require a non-empty tuple of scalar values"
                raise ValueError(msg)
            return self
        if self.operator is DocumentFilterOperator.CONTAINS:
            if not isinstance(self.value, str):
                msg = "contains filters require a string value"
                raise ValueError(msg)
            if not self.value.strip():
                msg = "contains filters require a non-empty string value"
                raise ValueError(msg)
            return self
        if not is_numeric_scalar(self.value):
            msg = f"{self.operator.value} filters require a numeric value"
            raise ValueError(msg)
        return self


class MetadataSelectionPlan(NullVectorModel):
    """Typed metadata filter plan used before retrieval."""

    raw_query: NonEmptyStr
    normalized_query: NonEmptyStr
    clauses: tuple[DocumentFilterClause, ...] = Field(default_factory=tuple)
    reasoning_summary: NonEmptyStr | None = None


class DocumentSelectionCandidate(NullVectorModel):
    """One candidate document returned by metadata selection."""

    document_id: NonEmptyStr
    score: NonNegativeFloat
    selection_reason: NonEmptyStr
    matched_metadata: dict[str, ScalarValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_matched_metadata(self) -> Self:
        for key in self.matched_metadata:
            if not key.strip():
                msg = "matched metadata keys must be non-empty"
                raise ValueError(msg)
        return self


class DocumentDescriptionRecord(NullVectorModel):
    """One collection-scoped document description record."""

    document_id: NonEmptyStr
    display_name: NonEmptyStr
    description_text: NonEmptyStr
    description_manifest_path: NonEmptyStr


class DescriptionSelectionMode(StrEnum):
    """Execution mode used for one description-selection run."""

    LLM = "llm"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class DescriptionSelectionCandidate(NullVectorModel):
    """One candidate document returned by description selection."""

    document_id: NonEmptyStr
    score: NonNegativeFloat
    reason: NonEmptyStr


class MetadataSelectionPlannerRequest(NullVectorModel):
    """Planner input for natural-language metadata selection."""

    query: NonEmptyStr
    allowed_fields: tuple[NonEmptyStr, ...]
    field_descriptions: dict[str, str] = Field(default_factory=dict)
    allowed_operators: tuple[DocumentFilterOperator, ...] = Field(
        default_factory=lambda: tuple(DocumentFilterOperator)
    )

    @model_validator(mode="after")
    def validate_field_descriptions(self) -> Self:
        allowed = set(self.allowed_fields)
        unknown = tuple(sorted(field for field in self.field_descriptions if field not in allowed))
        if unknown:
            msg = f"field_descriptions contains unknown fields: {unknown}"
            raise ValueError(msg)
        return self


class MetadataSelectionRequest(NullVectorModel):
    """Execution request for collection-level metadata selection."""

    collection_id: NonEmptyStr
    selection_run_id: NonEmptyStr
    plan: MetadataSelectionPlan
    allowed_fields: tuple[NonEmptyStr, ...]
    metadata_records: tuple[DocumentMetadataRecord, ...] = Field(default_factory=tuple)
    limit: PositiveInt = 10
    artifact_root: NonEmptyStr | None = None


class MetadataSelectionResponse(NullVectorModel):
    """Persisted metadata-selection result payload."""

    collection_id: NonEmptyStr
    selection_run_id: NonEmptyStr
    candidates: tuple[DocumentSelectionCandidate, ...]
    artifact_root: NonEmptyStr | None = None
    metadata_index_path: NonEmptyStr
    selection_plan_path: NonEmptyStr
    selection_results_path: NonEmptyStr


class DescriptionSelectionRequest(NullVectorModel):
    """Execution request for collection-level description selection."""

    collection_id: NonEmptyStr
    selection_run_id: NonEmptyStr
    query: NonEmptyStr
    descriptions: tuple[DocumentDescriptionRecord, ...]
    limit: PositiveInt = 10
    artifact_root: NonEmptyStr | None = None


class DescriptionSelectionResponse(NullVectorModel):
    """Persisted description-selection result payload."""

    collection_id: NonEmptyStr
    selection_run_id: NonEmptyStr
    candidates: tuple[DescriptionSelectionCandidate, ...]
    selection_mode: DescriptionSelectionMode
    artifact_root: NonEmptyStr | None = None
    description_index_path: NonEmptyStr
    selection_results_path: NonEmptyStr


class DocumentSemanticProxySource(NullVectorModel):
    """Artifact references used to build one semantic proxy."""

    document_id: NonEmptyStr
    display_name: NonEmptyStr
    description_manifest_path: NonEmptyStr
    tree_manifest_path: NonEmptyStr


class DocumentSemanticProxy(NullVectorModel):
    """One persisted-in-memory semantic proxy used for collection prefiltering."""

    document_id: NonEmptyStr
    display_name: NonEmptyStr
    description_text: NonEmptyStr
    summary_text: NonEmptyStr
    keywords: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    source_node_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    description_manifest_path: NonEmptyStr
    tree_manifest_path: NonEmptyStr


class DocumentPrefilterHit(NullVectorModel):
    """One ranked document hit returned by a semantic prefilter."""

    document_id: NonEmptyStr
    score: NonNegativeFloat
    matched_proxy_fields: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


class DocumentPrefilterRequest(NullVectorModel):
    """Execution request for collection-level semantic prefiltering."""

    collection_id: NonEmptyStr
    selection_run_id: NonEmptyStr
    query: NonEmptyStr
    proxies: tuple[DocumentSemanticProxy, ...]
    limit: PositiveInt = 10
    artifact_root: NonEmptyStr | None = None


class DocumentPrefilterResponse(NullVectorModel):
    """Persisted semantic-prefilter result payload."""

    collection_id: NonEmptyStr
    selection_run_id: NonEmptyStr
    hits: tuple[DocumentPrefilterHit, ...]
    artifact_root: NonEmptyStr | None = None
    semantic_proxy_index_path: NonEmptyStr
    semantic_prefilter_results_path: NonEmptyStr


__all__ = [
    "DescriptionSelectionCandidate",
    "DescriptionSelectionMode",
    "DescriptionSelectionRequest",
    "DescriptionSelectionResponse",
    "DocumentDescriptionRecord",
    "DocumentFilterClause",
    "DocumentFilterOperator",
    "DocumentMetadataRecord",
    "DocumentPrefilterHit",
    "DocumentPrefilterRequest",
    "DocumentPrefilterResponse",
    "DocumentSelectionCandidate",
    "DocumentSemanticProxy",
    "DocumentSemanticProxySource",
    "MetadataSelectionPlan",
    "MetadataSelectionPlannerRequest",
    "MetadataSelectionRequest",
    "MetadataSelectionResponse",
]
