"""Hierarchy, verification, and synthesis projection contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    Field,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

from nullvector.domain.common import (
    BoundingBox,
    CoerceTuple,
    GeometryCoordinateSpace,
    NodeOwnedSpan,
    NonEmptyStr,
    NullVectorModel,
    PageSourceAnchor,
    PageSpan,
    ScalarValue,
    Sha256Hex,
)
from nullvector.domain.events import DocumentEvent, EventSeverity, TrustTier
from nullvector.domain.ledger import OutlineEntry


class HierarchyOrigin(StrEnum):
    """Origin of a committed hierarchy node."""

    OUTLINE = "outline"
    INFERRED = "inferred"
    HYBRID = "hybrid"
    LLM_SYNTHESIZED = "llm_synthesized"


class NodeSummaryMethod(StrEnum):
    """How a committed node summary was produced."""

    PASSTHROUGH = "passthrough"
    LLM_LEAF = "llm_leaf"
    LLM_PARENT = "llm_parent"


class DecompositionMethod(StrEnum):
    """How large committed leaf nodes were subdivided."""

    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
    NONE = "none"


class VerificationStatus(StrEnum):
    """Outcome of a verification pass."""

    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REPAIR = "needs_repair"


class VerificationSeverity(StrEnum):
    """Severity level for verification findings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TreeSettings(NullVectorModel):
    """Settings for LLM-driven tree synthesis."""

    max_pages_per_leaf_node: PositiveInt = 10
    max_tokens_per_leaf_node: PositiveInt = 20000
    max_decomposition_depth: PositiveInt = 2
    hierarchy_chunk_size: PositiveInt = 10
    hierarchy_chunk_overlap: PositiveInt = 2
    hierarchy_chunking_threshold: PositiveInt = 15


class TreeCompactionSettings(NullVectorModel):
    """Deterministic controls for serving-tree compaction."""

    max_children_per_node: PositiveInt = 8
    require_summaries: bool = True


class TreeBuildRequest(NullVectorModel):
    """Input contract for a deterministic tree build."""

    acquisition_manifest_path: NonEmptyStr
    tree_run_id: NonEmptyStr
    summarize: bool = False
    settings: TreeSettings = Field(default_factory=TreeSettings)


class DecompositionBoundary(NullVectorModel):
    """Bounded subsection boundary returned by deterministic or LLM decomposition."""

    title: NonEmptyStr
    page_index: NonNegativeInt
    level_hint: PositiveInt | None = None


class HierarchyNode(NullVectorModel):
    """Internal hierarchy node used before projecting to NodeCard."""

    node_id: NonEmptyStr
    document_id: NonEmptyStr
    parent_id: NonEmptyStr | None = None
    path: Annotated[tuple[NonEmptyStr, ...], CoerceTuple]
    level: PositiveInt
    title: NonEmptyStr
    normalized_title: NonEmptyStr
    page_span: PageSpan
    owned_spans: Annotated[tuple[NodeOwnedSpan, ...], CoerceTuple] = Field(default_factory=tuple)
    source_anchors: Annotated[tuple[PageSourceAnchor, ...], CoerceTuple] = Field(
        default_factory=tuple
    )
    origin: HierarchyOrigin
    confidence: float = 0.0

    @model_validator(mode="after")
    def validate_hierarchy_node(self) -> Self:
        if not self.path:
            msg = "path must contain at least one segment"
            raise ValueError(msg)
        if not 0 <= self.confidence <= 1:
            msg = "confidence must be between 0 and 1"
            raise ValueError(msg)
        return self


class UnassignedPageSpan(NullVectorModel):
    """Explicit page coverage gap emitted when no verified node owns a page span."""

    document_id: NonEmptyStr
    reason: NonEmptyStr
    page_span: PageSpan


class HierarchyBuildReport(NullVectorModel):
    """Build summary for a tree run."""

    document_id: NonEmptyStr
    tree_run_id: NonEmptyStr
    committed_node_count: NonNegativeInt
    unassigned_span_count: NonNegativeInt
    synthesis_method: NonEmptyStr = "llm"
    notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


class NodeCard(NullVectorModel):
    """Compact hierarchical node contract used across parse and verification phases."""

    node_id: NonEmptyStr
    document_id: NonEmptyStr
    path: Annotated[tuple[NonEmptyStr, ...], CoerceTuple]
    level: PositiveInt
    title: NonEmptyStr
    page_span: PageSpan
    owned_spans: Annotated[tuple[NodeOwnedSpan, ...], CoerceTuple] = Field(default_factory=tuple)
    summary: str | None = None
    keywords: Annotated[tuple[NonEmptyStr, ...], CoerceTuple] = ()
    summary_method: NodeSummaryMethod | None = None
    summary_token_count: NonNegativeInt | None = None
    source_anchors: Annotated[tuple[PageSourceAnchor, ...], CoerceTuple] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def validate_path_and_anchors(self) -> Self:
        if not self.path:
            msg = "path must contain at least one segment"
            raise ValueError(msg)
        return self


class SemanticUsage(NullVectorModel):
    """Normalized token-usage snapshot for semantic operations."""

    input_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0
    total_tokens: NonNegativeInt = 0

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        computed_total = self.input_tokens + self.output_tokens
        if self.total_tokens not in (0, computed_total):
            msg = "total_tokens must be zero or equal input_tokens + output_tokens"
            raise ValueError(msg)
        if self.total_tokens == 0:
            object.__setattr__(self, "total_tokens", computed_total)
        return self


class NodeSummary(NullVectorModel):
    """Persistable summary payload for a committed hierarchy node."""

    node_id: NonEmptyStr
    summary: NonEmptyStr
    keywords: Annotated[tuple[NonEmptyStr, ...], CoerceTuple] = Field(default_factory=tuple)
    summary_method: NodeSummaryMethod
    token_count: NonNegativeInt
    estimated_token_count: NonNegativeInt
    exact_token_count: NonNegativeInt | None = None
    tokenizer_identity: NonEmptyStr
    gateway_provider_name: NonEmptyStr | None = None
    gateway_assurance_mode: NonEmptyStr | None = None
    gateway_audit_path: NonEmptyStr | None = None
    gateway_usage: SemanticUsage | None = None


class DecompositionReport(NullVectorModel):
    """Persistable audit report for large-node decomposition."""

    decomposed_node_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    new_child_count: NonNegativeInt = 0
    empty_parent_count: NonNegativeInt = 0
    decomposition_method: DecompositionMethod
    depth: NonNegativeInt = 0
    tokenizer_identity: NonEmptyStr | None = None
    gateway_provider_name: NonEmptyStr | None = None
    gateway_assurance_mode: NonEmptyStr | None = None
    gateway_usage: SemanticUsage | None = None
    gateway_audit_paths: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


class VisualRegionReference(NullVectorModel):
    """Stable reference to a visual region eligible for enrichment."""

    document_id: NonEmptyStr
    page_index: NonNegativeInt
    region_id: NonEmptyStr
    bbox: BoundingBox | None = None
    image_ref: NonEmptyStr | None = None
    asset_path: NonEmptyStr | None = None
    page_render_path: NonEmptyStr | None = None
    render_dpi: PositiveInt | None = None
    coordinate_space: GeometryCoordinateSpace = GeometryCoordinateSpace.UNROTATED_PAGE
    node_id: NonEmptyStr | None = None


class StructuredRegionInsight(NullVectorModel):
    """Non-authoritative structured insight produced from a visual region."""

    summary: NonEmptyStr
    labels: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    attributes: dict[str, ScalarValue] = Field(default_factory=dict)
    confidence: float | None = None

    @model_validator(mode="after")
    def validate_confidence(self) -> Self:
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            msg = "confidence must be between 0 and 1"
            raise ValueError(msg)
        return self


class VisualEnrichmentRequest(NullVectorModel):
    """Attachment-only enrichment request over one unresolved visual region."""

    request_id: NonEmptyStr
    region: VisualRegionReference
    prompt: NonEmptyStr
    node_id: NonEmptyStr | None = None
    metadata: dict[str, ScalarValue] = Field(default_factory=dict)


class VisualEnrichmentAttachment(NullVectorModel):
    """Non-authoritative visual insight attached to a node or region."""

    attachment_id: NonEmptyStr
    document_id: NonEmptyStr
    node_id: NonEmptyStr | None = None
    region_id: NonEmptyStr
    provider_identity: NonEmptyStr
    confidence: float | None = None
    authoritative: bool = False
    insight: StructuredRegionInsight
    audit_path: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_confidence(self) -> Self:
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            msg = "confidence must be between 0 and 1"
            raise ValueError(msg)
        return self


class VerificationIssue(NullVectorModel):
    """Single verification finding."""

    code: NonEmptyStr
    message: NonEmptyStr
    severity: VerificationSeverity
    page_span: PageSpan | None = None


class LLMVerificationAssistRecord(NullVectorModel):
    """Persistable grounded-evidence record for verification assists."""

    node_id: NonEmptyStr
    title: NonEmptyStr
    page_index: NonNegativeInt
    llm_verdict: NonEmptyStr
    llm_rationale: NonEmptyStr
    supporting_quotes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    grounded_quotes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    ungrounded_quotes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    accepted: bool = False


class TreeNodeVerificationResult(NullVectorModel):
    """Tree-specific verification result for a committed hierarchy node."""

    document_id: NonEmptyStr
    tree_run_id: NonEmptyStr
    subject_id: NonEmptyStr
    status: VerificationStatus
    issues: Annotated[tuple[VerificationIssue, ...], CoerceTuple] = Field(default_factory=tuple)
    covered_page_span: PageSpan | None = None
    notes: Annotated[tuple[NonEmptyStr, ...], CoerceTuple] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        has_error = any(issue.severity == VerificationSeverity.ERROR for issue in self.issues)
        if self.status == VerificationStatus.PASSED and has_error:
            msg = "passed verification results cannot contain error severity issues"
            raise ValueError(msg)
        if self.status != VerificationStatus.PASSED and not self.issues:
            msg = "non-passed verification results must include at least one issue"
            raise ValueError(msg)
        return self


class VerificationReport(NullVectorModel):
    """Document-level verification report for a committed tree build."""

    document_id: NonEmptyStr
    tree_run_id: NonEmptyStr
    status: VerificationStatus
    node_results: Annotated[tuple[TreeNodeVerificationResult, ...], CoerceTuple] = Field(
        default_factory=tuple
    )
    document_issues: Annotated[tuple[VerificationIssue, ...], CoerceTuple] = Field(
        default_factory=tuple
    )
    unassigned_spans: Annotated[tuple[UnassignedPageSpan, ...], CoerceTuple] = Field(
        default_factory=tuple
    )
    notes: Annotated[tuple[NonEmptyStr, ...], CoerceTuple] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if (
            self.status != VerificationStatus.PASSED
            and not self.node_results
            and not self.document_issues
            and not self.unassigned_spans
        ):
            msg = "non-passed verification reports must carry issues or unassigned spans"
            raise ValueError(msg)
        return self


class VerificationResult(NullVectorModel):
    """Structured verification output for a node or document-level check."""

    document_id: NonEmptyStr
    parse_run_id: NonEmptyStr
    subject_id: NonEmptyStr
    status: VerificationStatus
    issues: Annotated[tuple[VerificationIssue, ...], CoerceTuple] = Field(default_factory=tuple)
    covered_page_span: PageSpan | None = None
    notes: Annotated[tuple[NonEmptyStr, ...], CoerceTuple] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        has_error = any(issue.severity == VerificationSeverity.ERROR for issue in self.issues)
        if self.status == VerificationStatus.PASSED and has_error:
            msg = "passed verification results cannot contain error severity issues"
            raise ValueError(msg)
        if self.status != VerificationStatus.PASSED and not self.issues:
            msg = "non-passed verification results must include at least one issue"
            raise ValueError(msg)
        return self


class TreeRunIndex(NullVectorModel):
    """Tree-run registry entry enforcing tree_run_id uniqueness within an artifact namespace."""

    tree_run_id: NonEmptyStr
    document_id: NonEmptyStr
    registry_root: NonEmptyStr
    acquisition_manifest_path: NonEmptyStr
    acquisition_artifact_identity: NonEmptyStr
    acquisition_fingerprint_sha256: Sha256Hex
    settings_digest: Sha256Hex
    manifest_path: NonEmptyStr | None = None


class TreeBuildManifest(NullVectorModel):
    """Manifest for a tree build run."""

    tree_run_id: NonEmptyStr
    document_id: NonEmptyStr
    registry_root: NonEmptyStr
    acquisition_manifest_path: NonEmptyStr
    acquisition_artifact_identity: NonEmptyStr
    acquisition_fingerprint_sha256: Sha256Hex
    artifact_root: NonEmptyStr | None = None
    settings: TreeSettings
    settings_digest: Sha256Hex
    run_index_path: NonEmptyStr | None = None
    committed_hierarchy_path: NonEmptyStr | None = None
    node_cards_path: NonEmptyStr | None = None
    unassigned_spans_path: NonEmptyStr | None = None
    build_report_path: NonEmptyStr | None = None
    node_summaries_path: NonEmptyStr | None = None
    decomposition_report_path: NonEmptyStr | None = None
    committed_node_count: NonNegativeInt
    unassigned_span_count: NonNegativeInt


class TreeCompactionRequest(NullVectorModel):
    """Input contract for one tree-compaction run."""

    tree_manifest_path: NonEmptyStr
    compaction_run_id: NonEmptyStr
    settings: TreeCompactionSettings = Field(default_factory=TreeCompactionSettings)
    artifact_root: NonEmptyStr | None = None


class CompactedTreeNode(NullVectorModel):
    """Serving-oriented node derived from one or more canonical tree nodes."""

    serving_node_id: NonEmptyStr
    title: NonEmptyStr
    level: PositiveInt
    path: Annotated[tuple[NonEmptyStr, ...], CoerceTuple]
    page_span: PageSpan
    summary_text: str | None = None
    child_serving_node_ids: Annotated[tuple[NonEmptyStr, ...], CoerceTuple] = Field(
        default_factory=tuple
    )
    canonical_node_ids: Annotated[tuple[NonEmptyStr, ...], CoerceTuple] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def validate_mapping(self) -> Self:
        if not self.path:
            msg = "compacted tree nodes must include a non-empty path"
            raise ValueError(msg)
        if not self.canonical_node_ids:
            msg = "compacted tree nodes must map to at least one canonical node id"
            raise ValueError(msg)
        return self


class CompactedNodeMapping(NullVectorModel):
    """Flat serving-node to canonical-node mapping artifact."""

    serving_node_id: NonEmptyStr
    canonical_node_ids: Annotated[tuple[NonEmptyStr, ...], CoerceTuple] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def validate_canonical_node_ids(self) -> Self:
        if not self.canonical_node_ids:
            msg = "compacted node mappings must include at least one canonical node id"
            raise ValueError(msg)
        return self


class CompactedTreeManifest(NullVectorModel):
    """Manifest for one persisted serving-tree compaction run."""

    document_id: NonEmptyStr
    tree_run_id: NonEmptyStr
    compaction_run_id: NonEmptyStr
    artifact_root: NonEmptyStr | None = None
    compacted_tree_path: NonEmptyStr
    node_mapping_path: NonEmptyStr
    source_tree_manifest_path: NonEmptyStr


class SynthesisTextProjection(NullVectorModel):
    """Projected text surface derived from table-like or non-line blocks."""

    projection_id: NonEmptyStr
    content: NonEmptyStr
    reading_index: NonNegativeInt
    bbox: BoundingBox | None = None
    trust_tier: TrustTier


class SynthesisUnresolvedRegion(NullVectorModel):
    """Projection-safe unresolved region without provider-native payload leakage."""

    region_id: NonEmptyStr
    bbox: BoundingBox | None = None
    reason_code: NonEmptyStr
    severity: EventSeverity
    recommended_fallback: NonEmptyStr


class SynthesisTrustSummary(NullVectorModel):
    """Compact trust summary surfaced to tree synthesis."""

    dominant_trust_tier: TrustTier | None = None
    line_count_by_trust_tier: dict[TrustTier, NonNegativeInt] = Field(default_factory=dict)
    interpretive_content_present: bool = False


class SynthesisLine(NullVectorModel):
    """Projection line preserving offsets, layout cues, and normalized trust."""

    line_id: NonEmptyStr
    content: NonEmptyStr
    normalized_text: NonEmptyStr
    casefold_punct_text: NonEmptyStr
    page_index: NonNegativeInt
    reading_index: NonNegativeInt
    start_offset: NonNegativeInt
    end_offset: PositiveInt
    occurrence_index: NonNegativeInt
    bbox: BoundingBox | None = None
    top_y: float | None = None
    font_size: float | None = None
    layout_cues_available: bool = False
    trust_tier: TrustTier

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end_offset <= self.start_offset:
            msg = "end_offset must be greater than start_offset"
            raise ValueError(msg)
        return self


class SynthesisPage(NullVectorModel):
    """Projection-safe page substrate used for hierarchy construction."""

    page_index: NonNegativeInt
    page_label: str | None = None
    width: float
    height: float
    lines: tuple[SynthesisLine, ...] = Field(default_factory=tuple)
    table_text_projections: tuple[SynthesisTextProjection, ...] = Field(default_factory=tuple)
    trust_summary: SynthesisTrustSummary = Field(default_factory=SynthesisTrustSummary)
    unresolved_regions: tuple[SynthesisUnresolvedRegion, ...] = Field(default_factory=tuple)


class TreeSynthesisView(NullVectorModel):
    """Projection boundary protecting tree synthesis from provider payloads."""

    document_id: NonEmptyStr
    pages: tuple[SynthesisPage, ...] = Field(default_factory=tuple)
    outline_entries: tuple[OutlineEntry, ...] = Field(default_factory=tuple)
    projection_events: tuple[DocumentEvent, ...] = Field(default_factory=tuple)


__all__ = [
    "CompactedNodeMapping",
    "CompactedTreeManifest",
    "CompactedTreeNode",
    "DecompositionBoundary",
    "DecompositionMethod",
    "DecompositionReport",
    "HierarchyBuildReport",
    "HierarchyNode",
    "HierarchyOrigin",
    "LLMVerificationAssistRecord",
    "NodeCard",
    "NodeSummary",
    "NodeSummaryMethod",
    "SemanticUsage",
    "StructuredRegionInsight",
    "SynthesisLine",
    "SynthesisPage",
    "SynthesisTextProjection",
    "SynthesisTrustSummary",
    "SynthesisUnresolvedRegion",
    "TreeBuildManifest",
    "TreeBuildRequest",
    "TreeCompactionRequest",
    "TreeCompactionSettings",
    "TreeNodeVerificationResult",
    "TreeRunIndex",
    "TreeSettings",
    "TreeSynthesisView",
    "UnassignedPageSpan",
    "VerificationIssue",
    "VerificationReport",
    "VerificationResult",
    "VerificationSeverity",
    "VerificationStatus",
    "VisualEnrichmentAttachment",
    "VisualEnrichmentRequest",
    "VisualRegionReference",
]
