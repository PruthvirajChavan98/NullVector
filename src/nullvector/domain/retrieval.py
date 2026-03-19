"""Typed retrieval corpus, planning, and answer-citation contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveInt, model_validator

from nullvector.domain.common import (
    ContentSpan,
    NonEmptyStr,
    NullVectorModel,
    PageSpan,
    ScalarValue,
    Sha256Hex,
)
from nullvector.domain.events import TrustTier
from nullvector.domain.tree import VisualRegionReference


class RetrievalUnitType(StrEnum):
    """Normalized retrieval evidence families."""

    PAGE_TEXT = "page_text"
    NODE_TEXT = "node_text"
    NODE_SUMMARY = "node_summary"
    TABLE = "table"
    VISUAL = "visual"
    UNRESOLVED_VISUAL = "unresolved_visual"
    UNASSIGNED_SPAN = "unassigned_span"


class RetrievalModality(StrEnum):
    """Top-level modality used for planning and filtering."""

    TEXT = "text"
    TABLE = "table"
    VISUAL = "visual"
    MIXED = "mixed"


class RetrievalEvidence(NullVectorModel):
    """Single typed evidence unit available to retrieval and QA."""

    unit_id: NonEmptyStr
    document_id: NonEmptyStr
    unit_type: RetrievalUnitType
    modality: RetrievalModality
    page_span: PageSpan
    content_span: ContentSpan | None = None
    node_id: NonEmptyStr | None = None
    title: NonEmptyStr | None = None
    text: str | None = None
    keywords: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    trust_tier: TrustTier | None = None
    authoritative: bool = False
    interpretive: bool = False
    source_anchors: tuple[dict[str, object], ...] = Field(default_factory=tuple)
    visual_region: VisualRegionReference | None = None
    asset_path: NonEmptyStr | None = None
    page_render_path: NonEmptyStr | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class RetrievalCorpus(NullVectorModel):
    """Document-scoped retrieval corpus persisted as an artifact."""

    document_id: NonEmptyStr
    units: tuple[RetrievalEvidence, ...] = Field(default_factory=tuple)


class RetrievalManifest(NullVectorModel):
    """Manifest for a persisted retrieval corpus artifact set."""

    document_id: NonEmptyStr
    artifact_root: NonEmptyStr | None = None
    corpus_path: NonEmptyStr
    stats_path: NonEmptyStr
    unit_count: NonNegativeInt


class TreeSearchMode(StrEnum):
    """Execution mode used for one tree-search retrieval run."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"


class TreeSearchTerminationSignal(StrEnum):
    """Why one tree-search step or run terminated."""

    LEAF = "leaf"
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    MAX_DEPTH = "max_depth"
    NO_POSITIVE_FRONTIER = "no_positive_frontier"
    FALLBACK_TO_FLAT_RETRIEVAL = "fallback_to_flat_retrieval"


class TreeSearchRequest(NullVectorModel):
    """Input contract for one persisted tree-search retrieval run."""

    query: NonEmptyStr
    tree_manifest_path: NonEmptyStr
    retrieval_manifest_path: NonEmptyStr
    search_run_id: NonEmptyStr
    max_depth: PositiveInt = 4
    max_frontier_size: PositiveInt = 8
    max_selected_nodes: PositiveInt = 3
    retrieval_limit: PositiveInt = 10
    artifact_root: NonEmptyStr | None = None


class TreeSearchFrontierNode(NullVectorModel):
    """Bounded tree-search frontier node passed into ranking or gateway selection."""

    node_id: NonEmptyStr
    title: NonEmptyStr
    path: tuple[NonEmptyStr, ...]
    level: PositiveInt
    page_span: PageSpan
    summary_text: str | None = None
    keywords: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

    @model_validator(mode="before")
    @classmethod
    def _coerce_sequences(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for field_name in ("path", "keywords"):
            value = normalized.get(field_name)
            if isinstance(value, list):
                normalized[field_name] = tuple(value)
        return normalized


class TreeSearchTraceStep(NullVectorModel):
    """One auditable frontier-selection step within tree search."""

    step_index: NonNegativeInt
    frontier_node_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    selected_node_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    selection_reason: NonEmptyStr
    termination_signal: TreeSearchTerminationSignal | None = None


class TreeSearchCandidate(NullVectorModel):
    """One selected terminal tree node mapped back to retrieval evidence."""

    node_id: NonEmptyStr
    page_span: PageSpan
    retrieval_evidence_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    score: NonNegativeFloat


class TreeSearchResponse(NullVectorModel):
    """Persisted tree-search response containing trace and narrowed retrieval hits."""

    tree_run_id: NonEmptyStr
    document_id: NonEmptyStr
    trace: tuple[TreeSearchTraceStep, ...] = Field(default_factory=tuple)
    selected_nodes: tuple[TreeSearchCandidate, ...] = Field(default_factory=tuple)
    retrieval_hits: tuple[RetrievalHit, ...] = Field(default_factory=tuple)
    search_mode: TreeSearchMode
    artifact_root: NonEmptyStr | None = None
    trace_path: NonEmptyStr
    results_path: NonEmptyStr


class PreferenceScope(StrEnum):
    """Scope attached to one preference snippet."""

    GLOBAL = "global"
    TENANT = "tenant"
    USER = "user"
    DOMAIN_RULE = "domain_rule"


class PreferenceSnippet(NullVectorModel):
    """One bounded preference snippet used to bias tree search."""

    preference_id: NonEmptyStr
    scope: PreferenceScope
    text: NonEmptyStr
    priority: int = 0
    metadata: dict[str, ScalarValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        for key in self.metadata:
            if not key.strip():
                msg = "preference metadata keys must be non-empty"
                raise ValueError(msg)
        return self


class PreferenceSelectionRequest(NullVectorModel):
    """Execution request for deterministic preference snippet selection."""

    query: NonEmptyStr
    snippets: tuple[PreferenceSnippet, ...] = Field(default_factory=tuple)
    limit: PositiveInt = 4


class PreferenceSelectionResult(NullVectorModel):
    """Selected preference snippets plus an auditable selection reason."""

    selected_snippets: tuple[PreferenceSnippet, ...] = Field(default_factory=tuple)
    selection_reason: NonEmptyStr


class PreferenceAwareTreeSearchRequest(TreeSearchRequest):
    """Tree-search request extended with bounded preference snippets."""

    preference_snippets: tuple[PreferenceSnippet, ...] = Field(default_factory=tuple)
    max_preference_snippets: PositiveInt = 4


class PreferenceAwareTreeSearchTraceStep(TreeSearchTraceStep):
    """Tree-search trace step including the preference snippets applied."""

    applied_preference_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


class PreferenceAwareTreeSearchResponse(NullVectorModel):
    """Persisted preference-aware tree-search response."""

    tree_run_id: NonEmptyStr
    document_id: NonEmptyStr
    preference_selection: PreferenceSelectionResult
    trace: tuple[PreferenceAwareTreeSearchTraceStep, ...] = Field(default_factory=tuple)
    selected_nodes: tuple[TreeSearchCandidate, ...] = Field(default_factory=tuple)
    retrieval_hits: tuple[RetrievalHit, ...] = Field(default_factory=tuple)
    search_mode: TreeSearchMode
    artifact_root: NonEmptyStr | None = None
    preference_selection_path: NonEmptyStr
    trace_path: NonEmptyStr
    results_path: NonEmptyStr
    fell_back_to_base_tree_search: bool = False


class DocumentDescriptionMethod(StrEnum):
    """Generation path used for one persisted document description artifact."""

    LLM_FROM_SUMMARIES = "llm_from_summaries"
    LLM_FROM_NODE_CARDS = "llm_from_node_cards"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class DocumentDescriptionSettings(NullVectorModel):
    """Configuration for one document-description generation run."""

    max_source_nodes: PositiveInt = 8
    prefer_node_summaries: bool = True
    max_output_tokens: PositiveInt = 120
    require_gateway: bool = False


class DocumentDescriptionRequest(NullVectorModel):
    """Typed request for building one persisted document description."""

    acquisition_manifest_path: NonEmptyStr
    tree_manifest_path: NonEmptyStr
    description_run_id: NonEmptyStr
    settings: DocumentDescriptionSettings = Field(default_factory=DocumentDescriptionSettings)
    artifact_root: NonEmptyStr | None = None


class DocumentDescription(NullVectorModel):
    """Persisted document-level description derived from existing tree artifacts."""

    document_id: NonEmptyStr
    tree_run_id: NonEmptyStr
    source_manifest_paths: tuple[NonEmptyStr, ...]
    description_text: NonEmptyStr
    description_method: DocumentDescriptionMethod
    source_node_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    settings_digest: Sha256Hex


class DocumentDescriptionManifest(NullVectorModel):
    """Manifest for one persisted document-description artifact set."""

    document_id: NonEmptyStr
    description_run_id: NonEmptyStr
    artifact_root: NonEmptyStr | None = None
    description_path: NonEmptyStr
    source_tree_manifest_path: NonEmptyStr
    source_acquisition_manifest_path: NonEmptyStr


class QueryPlan(NullVectorModel):
    """Deterministic retrieval plan derived from one raw query."""

    raw_query: NonEmptyStr
    normalized_query: NonEmptyStr
    page_filter: PageSpan | None = None
    unit_types: tuple[RetrievalUnitType, ...] = Field(default_factory=tuple)
    modality_filters: tuple[RetrievalModality, ...] = Field(default_factory=tuple)
    title_like_phrases: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    quoted_phrases: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    structural_query: bool = False
    visual_query: bool = False
    table_query: bool = False
    requires_multimodal: bool = False


class RetrievalHit(NullVectorModel):
    """Scored retrieval match with deterministic scoring details."""

    unit: RetrievalEvidence
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    matched_terms: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


TreeSearchResponse.model_rebuild()
PreferenceAwareTreeSearchResponse.model_rebuild()


class AnswerCitation(NullVectorModel):
    """Grounded citation returned alongside QA answers."""

    document_id: NonEmptyStr
    unit_id: NonEmptyStr
    page_span: PageSpan
    page_label: NonEmptyStr
    node_id: NonEmptyStr | None = None
    quote: str | None = None
    asset_path: NonEmptyStr | None = None

    @model_validator(mode="before")
    @classmethod
    def _populate_page_label(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("page_label") is not None:
            return data
        page_span = data.get("page_span")
        if page_span is None:
            return data
        span = page_span if isinstance(page_span, PageSpan) else PageSpan.model_validate(page_span)
        start_page = span.start_page + 1
        end_page = span.end_page + 1
        page_label = str(start_page) if start_page == end_page else f"{start_page}-{end_page}"
        return {**data, "page_label": page_label}


__all__ = [
    "AnswerCitation",
    "DocumentDescription",
    "DocumentDescriptionManifest",
    "DocumentDescriptionMethod",
    "DocumentDescriptionRequest",
    "DocumentDescriptionSettings",
    "PreferenceAwareTreeSearchRequest",
    "PreferenceAwareTreeSearchResponse",
    "PreferenceAwareTreeSearchTraceStep",
    "PreferenceScope",
    "PreferenceSelectionRequest",
    "PreferenceSelectionResult",
    "PreferenceSnippet",
    "QueryPlan",
    "RetrievalCorpus",
    "RetrievalEvidence",
    "RetrievalHit",
    "RetrievalManifest",
    "RetrievalModality",
    "RetrievalUnitType",
    "TreeSearchCandidate",
    "TreeSearchFrontierNode",
    "TreeSearchMode",
    "TreeSearchRequest",
    "TreeSearchResponse",
    "TreeSearchTerminationSignal",
    "TreeSearchTraceStep",
]
