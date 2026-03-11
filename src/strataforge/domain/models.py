"""Authoritative typed contracts for bootstrap, parser, and tree phases."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    StringConstraints,
    model_validator,
)

from strataforge.constants import (
    DEFAULT_ARTIFACT_ROOT,
    EXPECTED_PYMUPDF_VERSION,
    EXPECTED_PYPDF_VERSION,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256Hex = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-f0-9]{64}$"),
]


class StrataModel(BaseModel):
    """Common strict model configuration."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class ParseJobLifecycle(StrEnum):
    """Lifecycle states for parse jobs."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PageExtractionMethod(StrEnum):
    """How page content was extracted."""

    NATIVE_TEXT = "native_text"
    OCR = "ocr"
    MIXED = "mixed"
    EMPTY = "empty"


class OcrMode(StrEnum):
    """OCR execution mode for a page."""

    NONE = "none"
    PARTIAL = "partial"
    FULL = "full"


class OutlineSource(StrEnum):
    """Parser source used for outline extraction."""

    PYMUPDF = "pymupdf"
    PYPDF = "pypdf"
    NONE = "none"


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
    """Deterministic trust mode chosen for Phase 02 hierarchy assembly."""

    OUTLINE_PRIMARY = "outline_primary"
    HYBRID = "hybrid"
    INFERRED_PRIMARY = "inferred_primary"


class TitleMatchTier(StrEnum):
    """Verification tier used to confirm a node title against source artifacts."""

    EXACT_NORMALIZED = "exact_normalized"
    CASEFOLD_PUNCT = "casefold_punct"
    TOKEN_CONTAINMENT = "token_containment"
    EDIT_DISTANCE = "edit_distance"
    NONE = "none"


class RepairStatus(StrEnum):
    """Auditable state of a bounded repair request/decision."""

    NOT_REQUESTED = "not_requested"
    REQUESTED_BUT_SKIPPED = "requested_but_skipped"
    NOOP_APPLIED = "noop_applied"
    PROPOSAL_GENERATED = "proposal_generated"
    PROPOSAL_REJECTED = "proposal_rejected"


class RepairKind(StrEnum):
    """Bounded repair classes allowed in Phase 02."""

    TITLE_NORMALIZATION = "title_normalization"
    ADJACENT_LEVEL_AMBIGUITY = "adjacent_level_ambiguity"
    PARTIAL_TOC_REPAIR = "partial_toc_repair"


class ParseJobState(StrataModel):
    """Progress-oriented parse job state tracked through the workflow lifecycle."""

    job_id: NonEmptyStr
    document_id: NonEmptyStr
    parse_run_id: NonEmptyStr
    lifecycle: ParseJobLifecycle
    current_step: NonEmptyStr | None = None
    retry_count: NonNegativeInt = 0
    error_message: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_error_state(self) -> Self:
        if self.lifecycle == ParseJobLifecycle.FAILED and self.error_message is None:
            msg = "failed parse jobs must include an error_message"
            raise ValueError(msg)
        if self.lifecycle != ParseJobLifecycle.FAILED and self.error_message is not None:
            msg = "error_message is only allowed when lifecycle is failed"
            raise ValueError(msg)
        return self


class ParseErrorCode(StrEnum):
    """Typed parse error codes for substrate failures."""

    CONFLICT = "conflict"
    INVALID_SOURCE = "invalid_source"
    MISSING_OCR_RUNTIME = "missing_ocr_runtime"
    EXTRACTION_FAILED = "extraction_failed"


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


class PageSpan(StrataModel):
    """Inclusive page span within a source document."""

    start_page: NonNegativeInt
    end_page: NonNegativeInt

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.end_page < self.start_page:
            msg = "end_page must be greater than or equal to start_page"
            raise ValueError(msg)
        return self


class PageSourceAnchor(StrataModel):
    """Grounding anchor for summaries and verification."""

    page: NonNegativeInt
    start_offset: NonNegativeInt
    end_offset: PositiveInt
    quote: NonEmptyStr

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end_offset <= self.start_offset:
            msg = "end_offset must be greater than start_offset"
            raise ValueError(msg)
        return self


class DocumentFingerprint(StrataModel):
    """Stable source fingerprint used for idempotency and provenance."""

    document_id: NonEmptyStr
    source_path: NonEmptyStr
    sha256: Sha256Hex
    file_size_bytes: NonNegativeInt
    page_count: NonNegativeInt


class OutlineEntry(StrataModel):
    """Normalized outline entry for either parser source."""

    level: PositiveInt
    title: str
    page_index: NonNegativeInt | None = None
    source: OutlineSource


class OutlineQualityReport(StrataModel):
    """Selection metrics for normalized outlines."""

    source: OutlineSource
    entry_count: NonNegativeInt
    null_destination_count: NonNegativeInt
    empty_title_count: NonNegativeInt
    non_monotonic_count: NonNegativeInt
    invalid_level_count: NonNegativeInt
    max_depth: NonNegativeInt
    score: int


class ParserSettings(StrataModel):
    """Deterministic parser settings captured in the manifest and settings digest."""

    ocr_languages: tuple[NonEmptyStr, ...] = ("eng",)
    tessdata_path: NonEmptyStr | None = None
    ocr_dpi: PositiveInt = 300
    min_text_chars: NonNegativeInt = 20
    min_word_count: NonNegativeInt = 5
    high_image_coverage_ratio: PositiveFloat = 0.65
    full_page_image_coverage_ratio: PositiveFloat = 0.98
    dense_small_vector_threshold: PositiveInt = 2000
    small_vector_max_area_ratio: PositiveFloat = 0.0005
    vector_scan_limit: PositiveInt = 5000
    sample_native_rawdict_every_n_pages: PositiveInt = 10
    pymupdf_version: NonEmptyStr = EXPECTED_PYMUPDF_VERSION
    pypdf_version: NonEmptyStr = EXPECTED_PYPDF_VERSION

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if not self.ocr_languages:
            msg = "ocr_languages must contain at least one language"
            raise ValueError(msg)
        if self.high_image_coverage_ratio > 1:
            msg = "high_image_coverage_ratio must be less than or equal to 1"
            raise ValueError(msg)
        if self.full_page_image_coverage_ratio > 1:
            msg = "full_page_image_coverage_ratio must be less than or equal to 1"
            raise ValueError(msg)
        if self.full_page_image_coverage_ratio < self.high_image_coverage_ratio:
            msg = (
                "full_page_image_coverage_ratio must be greater than or equal to "
                "high_image_coverage_ratio"
            )
            raise ValueError(msg)
        if self.small_vector_max_area_ratio > 1:
            msg = "small_vector_max_area_ratio must be less than or equal to 1"
            raise ValueError(msg)
        return self


class ParseRequest(StrataModel):
    """Input contract for deterministic parse runs."""

    source_path: NonEmptyStr
    parse_run_id: NonEmptyStr
    artifact_root: NonEmptyStr = DEFAULT_ARTIFACT_ROOT
    settings: ParserSettings = Field(default_factory=ParserSettings)


class ParseFailure(StrataModel):
    """Typed parse failure payload for substrate errors."""

    code: ParseErrorCode
    message: NonEmptyStr
    document_id: NonEmptyStr | None = None
    page_index: NonNegativeInt | None = None
    details: dict[str, str] = Field(default_factory=dict)


class ParseRunIndex(StrataModel):
    """Parse-run root index used to enforce global parse_run_id uniqueness."""

    parse_run_id: NonEmptyStr
    document_id: NonEmptyStr
    fingerprint_sha256: Sha256Hex
    settings_digest: Sha256Hex
    manifest_path: NonEmptyStr


class TreeSettings(StrataModel):
    """Tuneable deterministic thresholds and policies for Phase 02 tree synthesis."""

    outline_null_destination_rate_threshold: PositiveFloat = 0.15
    outline_high_agreement_threshold: PositiveFloat = 0.70
    outline_low_agreement_threshold: PositiveFloat = 0.30
    heading_score_keep_threshold: NonNegativeInt = 30
    heading_score_high_confidence_threshold: NonNegativeInt = 50
    title_token_containment_threshold: PositiveFloat = 0.60
    short_title_max_length_for_edit_distance: PositiveInt = 32
    short_title_edit_distance_threshold: PositiveInt = 2
    maximum_allowed_page_adjacency: PositiveInt = 1
    repeated_header_footer_min_repetitions: PositiveInt = 2
    top_of_page_line_limit: PositiveInt = 3

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
        if self.title_token_containment_threshold > 1:
            msg = "title_token_containment_threshold must be less than or equal to 1"
            raise ValueError(msg)
        if self.heading_score_high_confidence_threshold < self.heading_score_keep_threshold:
            msg = (
                "heading_score_high_confidence_threshold must be greater than or equal to "
                "heading_score_keep_threshold"
            )
            raise ValueError(msg)
        return self


class TreeBuildRequest(StrataModel):
    """Input contract for a deterministic Phase 02 tree build."""

    parse_manifest_path: NonEmptyStr
    tree_run_id: NonEmptyStr
    settings: TreeSettings = Field(default_factory=TreeSettings)


class TreeRunIndex(StrataModel):
    """Tree-run registry entry enforcing tree_run_id uniqueness within an artifact namespace."""

    tree_run_id: NonEmptyStr
    document_id: NonEmptyStr
    registry_root: NonEmptyStr
    parse_manifest_path: NonEmptyStr
    parse_artifact_identity: NonEmptyStr
    parse_fingerprint_sha256: Sha256Hex
    settings_digest: Sha256Hex
    manifest_path: NonEmptyStr


class NodeAnchor(StrataModel):
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


class HeadingScoreBreakdown(StrataModel):
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


class HeadingCandidate(StrataModel):
    """Deterministic heading candidate extracted from persisted Phase 01 artifacts."""

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


class RepairRequest(StrataModel):
    """Typed repair request envelope emitted by deterministic Phase 02 logic."""

    request_id: NonEmptyStr
    subject_id: NonEmptyStr
    repair_kind: RepairKind
    rationale: NonEmptyStr
    details: dict[str, str] = Field(default_factory=dict)


class RepairDecision(StrataModel):
    """Typed repair decision recorded for audit and later Phase 03 integration."""

    subject_id: NonEmptyStr
    status: RepairStatus
    repair_kind: RepairKind | None = None
    request_id: NonEmptyStr | None = None
    message: NonEmptyStr
    proposed_title: NonEmptyStr | None = None
    resolved_level: PositiveInt | None = None
    details: dict[str, str] = Field(default_factory=dict)


class HierarchyNode(StrataModel):
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
    source_anchors: tuple[PageSourceAnchor, ...] = Field(default_factory=tuple)
    origin: HierarchyOrigin
    confidence: float = 0.0
    verification_match_tier: TitleMatchTier = TitleMatchTier.NONE

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


class UnassignedPageSpan(StrataModel):
    """Explicit page coverage gap emitted when no verified node owns a page span."""

    document_id: NonEmptyStr
    reason: NonEmptyStr
    page_span: PageSpan


class HierarchyBuildReport(StrataModel):
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


class PageLedgerRow(StrataModel):
    """Canonical per-page extraction ledger entry."""

    document_id: NonEmptyStr
    parse_run_id: NonEmptyStr
    source_path: NonEmptyStr
    page_index: NonNegativeInt
    page_label: str | None = None
    extraction_method: PageExtractionMethod
    needs_ocr: bool = False
    native_text_available: bool = True
    ocr_mode: OcrMode = OcrMode.NONE
    ocr_reason_codes: tuple[NonEmptyStr, ...] = ()
    text_offset_start: NonNegativeInt
    text_offset_end: NonNegativeInt
    text_length: NonNegativeInt
    text_sha256: Sha256Hex
    native_text_sha256: Sha256Hex | None = None
    native_word_count: NonNegativeInt = 0
    native_char_count: NonNegativeInt = 0
    image_coverage_ratio: float = 0.0
    vector_path_count: NonNegativeInt = 0
    dense_small_vector_count: NonNegativeInt = 0
    render_artifact_path: str | None = None
    text_artifact_path: NonEmptyStr
    native_text_artifact_path: NonEmptyStr
    native_rawdict_artifact_path: str | None = None
    ocr_text_artifact_path: str | None = None
    ocr_rawdict_artifact_path: str | None = None
    ocr_render_artifact_path: str | None = None

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.text_offset_end < self.text_offset_start:
            msg = "text_offset_end must be greater than or equal to text_offset_start"
            raise ValueError(msg)
        if self.text_offset_end - self.text_offset_start != self.text_length:
            msg = "text_length must equal text_offset_end - text_offset_start"
            raise ValueError(msg)
        if self.extraction_method == PageExtractionMethod.EMPTY and self.text_length != 0:
            msg = "empty extraction rows must have zero text_length"
            raise ValueError(msg)
        if not 0 <= self.image_coverage_ratio <= 1:
            msg = "image_coverage_ratio must be between 0 and 1"
            raise ValueError(msg)
        if self.needs_ocr and self.ocr_mode == OcrMode.NONE:
            msg = "needs_ocr rows must record a non-none ocr_mode"
            raise ValueError(msg)
        if not self.needs_ocr and self.ocr_mode != OcrMode.NONE:
            msg = "rows without OCR must use ocr_mode 'none'"
            raise ValueError(msg)
        if self.ocr_mode == OcrMode.NONE and self.ocr_reason_codes:
            msg = "ocr_reason_codes are only allowed for OCR rows"
            raise ValueError(msg)
        return self


class NodeCard(StrataModel):
    """Compact hierarchical node contract used across parse and verification phases."""

    node_id: NonEmptyStr
    document_id: NonEmptyStr
    path: tuple[NonEmptyStr, ...]
    level: PositiveInt
    title: NonEmptyStr
    page_span: PageSpan
    summary: str | None = None
    keywords: tuple[NonEmptyStr, ...] = ()
    source_anchors: tuple[PageSourceAnchor, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_path_and_anchors(self) -> Self:
        if not self.path:
            msg = "path must contain at least one segment"
            raise ValueError(msg)
        if self.summary is not None and not self.source_anchors:
            msg = "summarized node cards must include at least one source anchor"
            raise ValueError(msg)
        return self


class VerificationIssue(StrataModel):
    """Single verification finding."""

    code: NonEmptyStr
    message: NonEmptyStr
    severity: VerificationSeverity
    page_span: PageSpan | None = None


class TreeNodeVerificationResult(StrataModel):
    """Tree-specific verification result for a committed hierarchy node."""

    document_id: NonEmptyStr
    tree_run_id: NonEmptyStr
    subject_id: NonEmptyStr
    status: VerificationStatus
    issues: tuple[VerificationIssue, ...] = Field(default_factory=tuple)
    covered_page_span: PageSpan | None = None
    notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

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


class VerificationReport(StrataModel):
    """Document-level verification report for a committed Phase 02 tree build."""

    document_id: NonEmptyStr
    tree_run_id: NonEmptyStr
    status: VerificationStatus
    node_results: tuple[TreeNodeVerificationResult, ...] = Field(default_factory=tuple)
    document_issues: tuple[VerificationIssue, ...] = Field(default_factory=tuple)
    unassigned_spans: tuple[UnassignedPageSpan, ...] = Field(default_factory=tuple)
    notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

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


class VerificationResult(StrataModel):
    """Structured verification output for a node or document-level check."""

    document_id: NonEmptyStr
    parse_run_id: NonEmptyStr
    subject_id: NonEmptyStr
    status: VerificationStatus
    issues: tuple[VerificationIssue, ...] = Field(default_factory=tuple)
    covered_page_span: PageSpan | None = None
    notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

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


class TreeBuildManifest(StrataModel):
    """Filesystem-backed manifest for a deterministic Phase 02 tree build."""

    tree_run_id: NonEmptyStr
    document_id: NonEmptyStr
    registry_root: NonEmptyStr
    parse_manifest_path: NonEmptyStr
    parse_artifact_identity: NonEmptyStr
    parse_fingerprint_sha256: Sha256Hex
    artifact_root: NonEmptyStr
    settings: TreeSettings
    settings_digest: Sha256Hex
    run_index_path: NonEmptyStr
    headings_path: NonEmptyStr
    raw_hierarchy_path: NonEmptyStr
    repair_requests_path: NonEmptyStr
    repair_decisions_path: NonEmptyStr
    repaired_hierarchy_path: NonEmptyStr
    committed_hierarchy_path: NonEmptyStr
    node_cards_path: NonEmptyStr
    unassigned_spans_path: NonEmptyStr
    verification_report_path: NonEmptyStr
    build_report_path: NonEmptyStr
    committed_node_count: NonNegativeInt
    unassigned_span_count: NonNegativeInt


class ParseRunManifest(StrataModel):
    """Filesystem-backed manifest for a deterministic parse run."""

    parse_run_id: NonEmptyStr
    document_id: NonEmptyStr
    artifact_root: NonEmptyStr
    fingerprint: DocumentFingerprint
    settings: ParserSettings
    settings_digest: Sha256Hex
    selected_outline_source: OutlineSource
    outline_quality_reports: tuple[OutlineQualityReport, ...]
    ledger_path: NonEmptyStr
    selected_outline_path: NonEmptyStr
    source_copy_path: NonEmptyStr
    pymupdf_outline_path: NonEmptyStr
    pymupdf_rich_outline_path: NonEmptyStr
    pypdf_outline_path: NonEmptyStr
    page_count: NonNegativeInt
