"""Parse-run contracts and the additive v2 canonical ledger surface."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    model_validator,
)

from nullvector.constants import (
    DEFAULT_ACQUISITION_ARTIFACT_ROOT,
    DEFAULT_ARTIFACT_ROOT,
    EXPECTED_PYMUPDF_VERSION,
    EXPECTED_PYPDF_VERSION,
)
from nullvector.domain.common import (
    BoundingBox,
    GeometryCoordinateSpace,
    NonEmptyStr,
    ScalarValue,
    Sha256Hex,
    StrataModel,
)
from nullvector.domain.events import (
    DocumentEvent,
    EventSeverity,
    ExtractionProvenance,
    GroundingEvidence,
    PageEvent,
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


class ParseErrorCode(StrEnum):
    """Typed parse error codes for substrate failures."""

    CONFLICT = "conflict"
    INVALID_SOURCE = "invalid_source"
    MISSING_OCR_RUNTIME = "missing_ocr_runtime"
    EXTRACTION_FAILED = "extraction_failed"


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


class AcquisitionSettings(StrataModel):
    """Deterministic settings for the native-first v2 acquisition runtime."""

    pymupdf_version: NonEmptyStr = EXPECTED_PYMUPDF_VERSION
    pypdf_version: NonEmptyStr = EXPECTED_PYPDF_VERSION
    emit_line_blocks: bool = True
    detect_tables: bool = True
    image_region_warning_threshold: PositiveFloat = 0.65
    dense_vector_threshold: PositiveInt = 2000
    small_vector_max_area_ratio: PositiveFloat = 0.0005
    vector_scan_limit: PositiveInt = 5000
    table_min_columns: PositiveInt = 2
    table_min_rows: PositiveInt = 2
    render_dpi: PositiveInt = 144

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if self.image_region_warning_threshold > 1:
            msg = "image_region_warning_threshold must be less than or equal to 1"
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


class SourceMetadata(StrataModel):
    """Stable source metadata persisted alongside the canonical document ledger."""

    source_path: NonEmptyStr
    file_size_bytes: NonNegativeInt
    mime_type: NonEmptyStr | None = None
    page_count: NonNegativeInt
    extra: dict[str, ScalarValue] = Field(default_factory=dict)


class AcquisitionRequest(StrataModel):
    """Input contract for deterministic v2 acquisition runs."""

    source_path: NonEmptyStr
    acquisition_run_id: NonEmptyStr
    artifact_root: NonEmptyStr = DEFAULT_ACQUISITION_ARTIFACT_ROOT
    provider_identity: NonEmptyStr = "native_pymupdf"
    settings: AcquisitionSettings = Field(default_factory=AcquisitionSettings)


class AcquisitionManifest(StrataModel):
    """Filesystem-backed acquisition manifest for the future v2 ingestion boundary."""

    source_fingerprint_sha256: Sha256Hex
    settings_digest: Sha256Hex
    acquisition_provider_identity: NonEmptyStr
    enrichment_providers: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    selected_outline_source: OutlineSource | None = None
    outline_quality_reports: tuple[OutlineQualityReport, ...] = Field(default_factory=tuple)
    selected_outline_entries: tuple[OutlineEntry, ...] = Field(default_factory=tuple)
    ledger_artifact_path: NonEmptyStr | None = None
    outline_artifact_paths: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    event_stream_path: NonEmptyStr | None = None


class AcquisitionRunIndex(StrataModel):
    """Run-root index used to enforce global acquisition_run_id uniqueness."""

    acquisition_run_id: NonEmptyStr
    document_id: NonEmptyStr
    source_fingerprint_sha256: Sha256Hex
    settings_digest: Sha256Hex
    manifest_path: NonEmptyStr


class AcquisitionRunManifest(StrataModel):
    """Filesystem-backed manifest for a deterministic v2 acquisition run."""

    acquisition_run_id: NonEmptyStr
    document_id: NonEmptyStr
    artifact_root: NonEmptyStr
    source_fingerprint: DocumentFingerprint
    settings: AcquisitionSettings
    settings_digest: Sha256Hex
    provider_identity: NonEmptyStr
    ledger_path: NonEmptyStr
    source_copy_path: NonEmptyStr
    event_stream_path: NonEmptyStr
    selected_outline_source: OutlineSource
    outline_quality_reports: tuple[OutlineQualityReport, ...]
    selected_outline_path: NonEmptyStr
    pymupdf_outline_path: NonEmptyStr
    pymupdf_rich_outline_path: NonEmptyStr
    pypdf_outline_path: NonEmptyStr
    page_count: NonNegativeInt
    projection_view_path: NonEmptyStr | None = None
    canonical_text_substrate_path: NonEmptyStr | None = None


class TextBlock(StrataModel):
    """Normalized text block in the canonical acquisition ledger."""

    block_type: Literal["text_block"] = "text_block"
    block_id: NonEmptyStr
    bbox: BoundingBox
    content: NonEmptyStr
    reading_index: NonNegativeInt
    line_count: NonNegativeInt
    word_count: NonNegativeInt
    provenance: ExtractionProvenance
    grounding: GroundingEvidence


class LineBlock(StrataModel):
    """Optional canonical line-level artifact for stable offsets and layout cues."""

    block_type: Literal["line_block"] = "line_block"
    line_id: NonEmptyStr
    bbox: BoundingBox
    content: NonEmptyStr
    reading_index: NonNegativeInt
    occurrence_index: NonNegativeInt
    top_y: float | None = None
    font_size: float | None = None
    font_family_hint: NonEmptyStr | None = None
    provenance: ExtractionProvenance


class TableArtifact(StrataModel):
    """Deterministically recovered table-like content."""

    block_type: Literal["table_artifact"] = "table_artifact"
    table_id: NonEmptyStr
    bbox: BoundingBox
    reading_index: NonNegativeInt
    rows: tuple[tuple[str, ...], ...] = Field(default_factory=tuple)
    markdown_projection: str | None = None
    provenance: ExtractionProvenance
    grounding: GroundingEvidence

    @model_validator(mode="after")
    def validate_table_content(self) -> Self:
        if not self.rows and self.markdown_projection is None:
            msg = "table artifacts must define rows or markdown_projection"
            raise ValueError(msg)
        return self


class VisualArtifact(StrataModel):
    """Canonical record for a visual region that may require enrichment."""

    block_type: Literal["visual_artifact"] = "visual_artifact"
    visual_id: NonEmptyStr
    bbox: BoundingBox
    reading_index: NonNegativeInt
    kind_hint: NonEmptyStr
    image_ref: NonEmptyStr
    asset_path: NonEmptyStr | None = None
    page_render_path: NonEmptyStr | None = None
    render_dpi: PositiveInt | None = None
    coordinate_space: GeometryCoordinateSpace = GeometryCoordinateSpace.UNROTATED_PAGE
    needs_enrichment: bool = False
    provenance: ExtractionProvenance


class UnresolvedRegion(StrataModel):
    """Typed incompleteness contract for unresolved or unsafe-to-recover regions."""

    block_type: Literal["unresolved_region"] = "unresolved_region"
    region_id: NonEmptyStr
    bbox: BoundingBox
    reason_code: NonEmptyStr
    severity: EventSeverity
    recommended_fallback: NonEmptyStr
    reading_index: NonNegativeInt | None = None
    asset_path: NonEmptyStr | None = None
    page_render_path: NonEmptyStr | None = None
    render_dpi: PositiveInt | None = None
    coordinate_space: GeometryCoordinateSpace = GeometryCoordinateSpace.UNROTATED_PAGE
    provenance: ExtractionProvenance


class CanonicalTextPage(StrataModel):
    """Authoritative page-local text substrate for downstream tree and semantic use."""

    page_index: NonNegativeInt
    page_label: str | None = None
    text: str
    text_sha256: Sha256Hex
    lines: tuple[CanonicalTextLine, ...] = Field(default_factory=tuple)


class CanonicalTextLine(StrataModel):
    """Stable downstream text line with offsets and layout cues."""

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

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end_offset <= self.start_offset:
            msg = "end_offset must be greater than start_offset"
            raise ValueError(msg)
        return self


class CanonicalTextSubstrate(StrataModel):
    """Persisted, projection-safe text substrate with stable offsets by page."""

    document_id: NonEmptyStr
    pages: tuple[CanonicalTextPage, ...] = Field(default_factory=tuple)


PageBlock = Annotated[
    TextBlock | LineBlock | TableArtifact | VisualArtifact | UnresolvedRegion,
    Field(discriminator="block_type"),
]


class CanonicalPage(StrataModel):
    """Authoritative per-page unit in the v2 canonical document ledger."""

    page_index: NonNegativeInt
    page_label: str | None = None
    width: float
    height: float
    rotation: float = 0.0
    native_available: bool
    blocks: tuple[PageBlock, ...] = Field(default_factory=tuple)
    events: tuple[PageEvent, ...] = Field(default_factory=tuple)


class CanonicalDocumentLedger(StrataModel):
    """Authoritative ingestion boundary for acquisition and enrichment outputs."""

    ledger_version: NonEmptyStr = "canonical-document-ledger.v2alpha1"
    document_id: NonEmptyStr
    source_fingerprint: DocumentFingerprint
    source_metadata: SourceMetadata
    acquisition_manifest: AcquisitionManifest
    pages: tuple[CanonicalPage, ...] = Field(default_factory=tuple)
    document_events: tuple[DocumentEvent, ...] = Field(default_factory=tuple)


__all__ = [
    "AcquisitionManifest",
    "AcquisitionRequest",
    "AcquisitionRunIndex",
    "AcquisitionRunManifest",
    "AcquisitionSettings",
    "CanonicalDocumentLedger",
    "CanonicalPage",
    "CanonicalTextLine",
    "CanonicalTextPage",
    "CanonicalTextSubstrate",
    "DocumentFingerprint",
    "LineBlock",
    "OcrMode",
    "OutlineEntry",
    "OutlineQualityReport",
    "OutlineSource",
    "PageBlock",
    "PageExtractionMethod",
    "PageLedgerRow",
    "ParseErrorCode",
    "ParseFailure",
    "ParseJobLifecycle",
    "ParseJobState",
    "ParseRequest",
    "ParseRunIndex",
    "ParseRunManifest",
    "ParserSettings",
    "SourceMetadata",
    "TableArtifact",
    "TextBlock",
    "UnresolvedRegion",
    "VisualArtifact",
]
