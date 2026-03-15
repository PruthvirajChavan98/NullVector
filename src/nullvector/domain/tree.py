"""Hierarchy, verification, and synthesis projection contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import (
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)

from nullvector.domain.common import (
    BoundingBox,
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


class AnchorSource(StrEnum):
    """Artifact source used to derive a deterministic heading anchor."""

    TEXT = "text"
    RAWDICT = "rawdict"


class HeadingSourceKind(StrEnum):
    """Source family that produced a heading candidate."""

    OUTLINE = "outline"
    TEXT = "text"
    RAWDICT = "rawdict"


class HierarchyOrigin(StrEnum):
    """Origin of a committed hierarchy node."""

    OUTLINE = "outline"
    INFERRED = "inferred"
    HYBRID = "hybrid"


class OutlineTrustMode(StrEnum):
    """Deterministic trust mode chosen for hierarchy assembly."""

    OUTLINE_PRIMARY = "outline_primary"
    HYBRID = "hybrid"
    INFERRED_PRIMARY = "inferred_primary"
    TOC_RECONCILED = "toc_reconciled"


class OutlineAnchorStatus(StrEnum):
    """Physical anchoring state for an outline entry."""

    ANCHORED_TO_PHYSICAL_TEXT = "anchored_to_physical_text"
    OUTLINE_KNOWN_BUT_UNANCHORED = "outline_known_but_unanchored"
    REJECTED = "rejected"


class TocDetectionMethod(StrEnum):
    """How TOC pages were classified."""

    DETERMINISTIC = "deterministic"
    HYBRID = "hybrid"
    LLM_ONLY = "llm_only"


class TocParseMethod(StrEnum):
    """How TOC text was parsed into structural entries."""

    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"


class TitleMatchTier(StrEnum):
    """Verification tier used to confirm a node title against source artifacts."""

    EXACT_NORMALIZED = "exact_normalized"
    CASEFOLD_PUNCT = "casefold_punct"
    TOKEN_CONTAINMENT = "token_containment"
    EDIT_DISTANCE = "edit_distance"
    LLM_VERIFIED = "llm_verified"
    NONE = "none"


class RepairStatus(StrEnum):
    """Auditable state of a bounded repair request/decision."""

    NOT_REQUESTED = "not_requested"
    REQUESTED_BUT_SKIPPED = "requested_but_skipped"
    NOOP_APPLIED = "noop_applied"
    PROPOSAL_GENERATED = "proposal_generated"
    PROPOSAL_REJECTED = "proposal_rejected"


class RepairKind(StrEnum):
    """Bounded repair classes allowed in the tree pipeline."""

    TITLE_NORMALIZATION = "title_normalization"
    ADJACENT_LEVEL_AMBIGUITY = "adjacent_level_ambiguity"
    PARTIAL_TOC_REPAIR = "partial_toc_repair"


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


class HierarchyStrategy(StrEnum):
    """Typed orchestration strategies for hierarchy construction."""

    OUTLINE_WITH_TOC_RECONCILIATION = "outline_with_toc_reconciliation"
    OUTLINE_ONLY = "outline_only"
    TOC_DERIVED = "toc_derived"
    INFERRED_WITH_LLM_ASSIST = "inferred_with_llm_assist"
    INFERRED_DETERMINISTIC = "inferred_deterministic"


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
    """Tuneable deterministic thresholds and policies for tree synthesis."""

    outline_null_destination_rate_threshold: PositiveFloat = 0.15
    outline_high_agreement_threshold: PositiveFloat = 0.70
    outline_low_agreement_threshold: PositiveFloat = 0.30
    heading_score_keep_threshold: NonNegativeInt = 30
    heading_score_high_confidence_threshold: NonNegativeInt = 50
    max_pages_per_leaf_node: PositiveInt = 10
    max_tokens_per_leaf_node: PositiveInt = 20000
    max_decomposition_depth: PositiveInt = 2

    @model_validator(mode="after")
    def validate_thresholds(self) -> Self:
        if self.outline_high_agreement_threshold > 1:
            msg = "outline_high_agreement_threshold must be less than or equal to 1"
            raise ValueError(msg)
        if self.outline_low_agreement_threshold > 1:
            msg = "outline_low_agreement_threshold must be less than or equal to 1"
            raise ValueError(msg)
        if self.outline_high_agreement_threshold < self.outline_low_agreement_threshold:
            msg = (
                "outline_high_agreement_threshold must be greater than or equal to "
                "outline_low_agreement_threshold"
            )
            raise ValueError(msg)
        if self.heading_score_high_confidence_threshold < self.heading_score_keep_threshold:
            msg = (
                "heading_score_high_confidence_threshold must be greater than or equal to "
                "heading_score_keep_threshold"
            )
            raise ValueError(msg)
        return self


class TreeBuildRequest(NullVectorModel):
    """Input contract for a deterministic tree build."""

    acquisition_manifest_path: NonEmptyStr
    tree_run_id: NonEmptyStr
    summarize: bool = False
    settings: TreeSettings = Field(default_factory=TreeSettings)


class TocPageScore(NullVectorModel):
    """Deterministic and hybrid TOC-likeness signals for a single page."""

    page_index: NonNegativeInt
    pattern_match_count: NonNegativeInt
    leader_dot_density: float = 0.0
    numbering_density: float = 0.0
    font_uniformity_signal: float = 0.0
    consecutive_page_bonus: float = 0.0
    repeated_header_penalty: float = 0.0
    final_score: float
    classified_as_toc: bool = False
    classification_reason: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        bounded_values = {
            "leader_dot_density": self.leader_dot_density,
            "numbering_density": self.numbering_density,
            "font_uniformity_signal": self.font_uniformity_signal,
            "consecutive_page_bonus": self.consecutive_page_bonus,
            "repeated_header_penalty": self.repeated_header_penalty,
            "final_score": self.final_score,
        }
        for field_name, value in bounded_values.items():
            if not 0 <= value <= 1:
                msg = f"{field_name} must be between 0 and 1"
                raise ValueError(msg)
        return self


class TocDetectionResult(NullVectorModel):
    """Persistable TOC detection result over the leading parse artifact pages."""

    toc_page_indices: tuple[NonNegativeInt, ...] = ()
    toc_content: str | None = None
    detection_method: TocDetectionMethod
    page_scores: tuple[TocPageScore, ...] = Field(default_factory=tuple)
    has_page_numbers: bool = False


class TocParsedEntry(NullVectorModel):
    """Single parsed entry recovered from TOC text."""

    structure: str | None = None
    title: NonEmptyStr
    page_number: NonNegativeInt | None = None


class OutlineAnchorRecord(NullVectorModel):
    """Auditable anchoring outcome for one outline entry."""

    document_id: NonEmptyStr
    title: NonEmptyStr
    normalized_title: NonEmptyStr
    page_index: NonNegativeInt | None = None
    source: NonEmptyStr
    status: OutlineAnchorStatus
    anchor: NodeAnchor | None = None
    reason: NonEmptyStr | None = None


class DecompositionBoundary(NullVectorModel):
    """Bounded subsection boundary returned by deterministic or LLM decomposition."""

    title: NonEmptyStr
    page_index: NonNegativeInt
    level_hint: PositiveInt | None = None


class TocReconciliationResult(NullVectorModel):
    """Deterministic TOC-to-physical-page reconciliation result."""

    parsed_entries: tuple[TocParsedEntry, ...] = Field(default_factory=tuple)
    offset: int | None = None
    offset_confidence: float = 0.0
    reconciled_candidates: tuple[HeadingCandidate, ...] = Field(default_factory=tuple)
    parse_method: TocParseMethod

    @model_validator(mode="after")
    def validate_offset_confidence(self) -> Self:
        if not 0 <= self.offset_confidence <= 1:
            msg = "offset_confidence must be between 0 and 1"
            raise ValueError(msg)
        return self


class NodeAnchor(NullVectorModel):
    """Deterministic heading anchor used to start a hierarchy node."""

    page: NonNegativeInt
    start_offset: NonNegativeInt
    end_offset: PositiveInt
    anchor_text: NonEmptyStr
    anchor_source: AnchorSource
    occurrence_index: NonNegativeInt

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end_offset <= self.start_offset:
            msg = "end_offset must be greater than start_offset"
            raise ValueError(msg)
        return self


class HeadingScoreBreakdown(NullVectorModel):
    """Explicit signal breakdown for heading candidate scoring."""

    numbering_signal: int = 0
    isolation_signal: int = 0
    short_line_signal: int = 0
    title_case_signal: int = 0
    uppercase_signal: int = 0
    punctuation_penalty: int = 0
    repeated_header_footer_penalty: int = 0
    toc_overlap_signal: int = 0
    layout_signal: int = 0
    layout_cues_available: bool = False
    final_score: int


class HeadingCandidate(NullVectorModel):
    """Deterministic heading candidate extracted from persisted source artifacts."""

    document_id: NonEmptyStr
    page_index: NonNegativeInt
    title: NonEmptyStr
    normalized_title: NonEmptyStr
    anchor: NodeAnchor
    source_kind: HeadingSourceKind
    level_hint: PositiveInt | None = None
    outline_level_hint: PositiveInt | None = None
    score_breakdown: HeadingScoreBreakdown
    keep: bool = False
    high_confidence: bool = False


class RepairRequest(NullVectorModel):
    """Typed repair request envelope emitted by deterministic tree logic."""

    request_id: NonEmptyStr
    subject_id: NonEmptyStr
    repair_kind: RepairKind
    rationale: NonEmptyStr
    details: dict[str, str] = Field(default_factory=dict)


class RepairDecision(NullVectorModel):
    """Typed repair decision recorded for audit and later gateway integration."""

    subject_id: NonEmptyStr
    status: RepairStatus
    repair_kind: RepairKind | None = None
    request_id: NonEmptyStr | None = None
    message: NonEmptyStr
    proposed_title: NonEmptyStr | None = None
    resolved_level: PositiveInt | None = None
    details: dict[str, str] = Field(default_factory=dict)


class HierarchyNode(NullVectorModel):
    """Internal verified hierarchy node used before projecting to NodeCard."""

    node_id: NonEmptyStr
    document_id: NonEmptyStr
    parent_id: NonEmptyStr | None = None
    path: tuple[NonEmptyStr, ...]
    level: PositiveInt
    title: NonEmptyStr
    normalized_title: NonEmptyStr
    page_span: PageSpan
    heading_anchor: NodeAnchor
    owned_spans: tuple[NodeOwnedSpan, ...] = Field(default_factory=tuple)
    source_anchors: tuple[PageSourceAnchor, ...] = Field(default_factory=tuple)
    origin: HierarchyOrigin
    confidence: float = 0.0
    verification_match_tier: TitleMatchTier = TitleMatchTier.NONE

    @field_validator("path", "owned_spans", "source_anchors", mode="before")
    @classmethod
    def _coerce_sequence_fields(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_hierarchy_node(self) -> Self:
        if not self.path:
            msg = "path must contain at least one segment"
            raise ValueError(msg)
        if not self.source_anchors:
            msg = "hierarchy nodes must include at least one source anchor"
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
    """Deterministic build summary and ambiguity accounting for a tree run."""

    document_id: NonEmptyStr
    tree_run_id: NonEmptyStr
    outline_trust_mode: OutlineTrustMode
    candidate_count: NonNegativeInt
    outline_candidate_count: NonNegativeInt
    inferred_candidate_count: NonNegativeInt
    selected_candidate_count: NonNegativeInt
    kept_candidate_count: NonNegativeInt
    high_confidence_candidate_count: NonNegativeInt
    candidates_with_layout_cues: NonNegativeInt
    candidates_without_layout_cues: NonNegativeInt
    committed_node_count: NonNegativeInt
    unassigned_span_count: NonNegativeInt
    ambiguity_count: NonNegativeInt
    notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


class StrategyRationale(NullVectorModel):
    """Deterministic rationale used for strategy selection."""

    reasons: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    outline_available: bool
    toc_available: bool
    gateway_available: bool


class StrategyExecutionReport(NullVectorModel):
    """Auditable record of attempted and selected hierarchy strategies."""

    attempted_strategies: tuple[HierarchyStrategy, ...]
    selected_strategy: HierarchyStrategy
    rationale: StrategyRationale
    fallback_reasons: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


class NodeCard(NullVectorModel):
    """Compact hierarchical node contract used across parse and verification phases."""

    node_id: NonEmptyStr
    document_id: NonEmptyStr
    path: tuple[NonEmptyStr, ...]
    level: PositiveInt
    title: NonEmptyStr
    page_span: PageSpan
    owned_spans: tuple[NodeOwnedSpan, ...] = Field(default_factory=tuple)
    summary: str | None = None
    keywords: tuple[NonEmptyStr, ...] = ()
    summary_method: NodeSummaryMethod | None = None
    summary_token_count: NonNegativeInt | None = None
    source_anchors: tuple[PageSourceAnchor, ...] = Field(default_factory=tuple)

    @field_validator("path", "owned_spans", "keywords", "source_anchors", mode="before")
    @classmethod
    def _coerce_sequence_fields(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_path_and_anchors(self) -> Self:
        if not self.path:
            msg = "path must contain at least one segment"
            raise ValueError(msg)
        if self.summary is not None and not self.source_anchors:
            msg = "summarized node cards must include at least one source anchor"
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
            return self.model_copy(update={"total_tokens": computed_total})
        return self


class NodeSummary(NullVectorModel):
    """Persistable summary payload for a committed hierarchy node."""

    node_id: NonEmptyStr
    summary: NonEmptyStr
    keywords: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    summary_method: NodeSummaryMethod
    token_count: NonNegativeInt
    estimated_token_count: NonNegativeInt
    exact_token_count: NonNegativeInt | None = None
    tokenizer_identity: NonEmptyStr
    gateway_provider_name: NonEmptyStr | None = None
    gateway_assurance_mode: NonEmptyStr | None = None
    gateway_audit_path: NonEmptyStr | None = None
    gateway_usage: SemanticUsage | None = None

    @field_validator("keywords", mode="before")
    @classmethod
    def _coerce_keywords(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


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
    bbox: BoundingBox
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
    issues: tuple[VerificationIssue, ...] = Field(default_factory=tuple)
    covered_page_span: PageSpan | None = None
    notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

    @field_validator("issues", "notes", mode="before")
    @classmethod
    def _coerce_result_sequences(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

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
    node_results: tuple[TreeNodeVerificationResult, ...] = Field(default_factory=tuple)
    document_issues: tuple[VerificationIssue, ...] = Field(default_factory=tuple)
    unassigned_spans: tuple[UnassignedPageSpan, ...] = Field(default_factory=tuple)
    notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

    @field_validator(
        "node_results",
        "document_issues",
        "unassigned_spans",
        "notes",
        mode="before",
    )
    @classmethod
    def _coerce_report_sequences(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

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
    issues: tuple[VerificationIssue, ...] = Field(default_factory=tuple)
    covered_page_span: PageSpan | None = None
    notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

    @field_validator("issues", "notes", mode="before")
    @classmethod
    def _coerce_result_sequences(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

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
    """Filesystem-backed manifest for a deterministic tree build."""

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
    headings_path: NonEmptyStr | None = None
    raw_hierarchy_path: NonEmptyStr | None = None
    repair_requests_path: NonEmptyStr | None = None
    repair_decisions_path: NonEmptyStr | None = None
    repaired_hierarchy_path: NonEmptyStr | None = None
    committed_hierarchy_path: NonEmptyStr | None = None
    node_cards_path: NonEmptyStr | None = None
    unassigned_spans_path: NonEmptyStr | None = None
    verification_report_path: NonEmptyStr | None = None
    build_report_path: NonEmptyStr | None = None
    toc_detection_path: NonEmptyStr | None = None
    toc_reconciliation_path: NonEmptyStr | None = None
    llm_verification_assists_path: NonEmptyStr | None = None
    node_summaries_path: NonEmptyStr | None = None
    strategy_execution_report_path: NonEmptyStr | None = None
    decomposition_report_path: NonEmptyStr | None = None
    committed_node_count: NonNegativeInt
    unassigned_span_count: NonNegativeInt


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
    bbox: BoundingBox
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
    bbox: BoundingBox
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
    "AnchorSource",
    "DecompositionBoundary",
    "DecompositionMethod",
    "DecompositionReport",
    "HeadingCandidate",
    "HeadingScoreBreakdown",
    "HeadingSourceKind",
    "HierarchyBuildReport",
    "HierarchyNode",
    "HierarchyOrigin",
    "HierarchyStrategy",
    "LLMVerificationAssistRecord",
    "NodeAnchor",
    "NodeCard",
    "NodeSummary",
    "NodeSummaryMethod",
    "OutlineAnchorRecord",
    "OutlineAnchorStatus",
    "OutlineTrustMode",
    "RepairDecision",
    "RepairKind",
    "RepairRequest",
    "RepairStatus",
    "SemanticUsage",
    "StrategyExecutionReport",
    "StrategyRationale",
    "StructuredRegionInsight",
    "SynthesisLine",
    "SynthesisPage",
    "SynthesisTextProjection",
    "SynthesisTrustSummary",
    "SynthesisUnresolvedRegion",
    "TitleMatchTier",
    "TocDetectionMethod",
    "TocDetectionResult",
    "TocPageScore",
    "TocParseMethod",
    "TocParsedEntry",
    "TocReconciliationResult",
    "TreeBuildManifest",
    "TreeBuildRequest",
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
