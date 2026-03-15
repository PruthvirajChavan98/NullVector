"""Typed provenance, trust, and event contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, NonNegativeInt, model_validator

from nullvector.domain.common import NonEmptyStr, NullVectorModel, ScalarValue


class EventSeverity(StrEnum):
    """Generic severity level for acquisition, projection, and framework events."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SourceTrack(StrEnum):
    """Normalized acquisition track for persisted content provenance."""

    NATIVE = "native"
    EXTERNAL_OCR = "external_ocr"
    VISUAL_ENRICHMENT = "visual_enrichment"


class ContentAuthoritativeness(StrEnum):
    """How strongly a content block should be trusted as source truth."""

    AUTHORITATIVE = "authoritative"
    SUPPLEMENTAL = "supplemental"
    INTERPRETIVE = "interpretive"


class TrustTier(StrEnum):
    """Normalized trust classes exposed to tree synthesis."""

    NATIVE_EXACT = "native_exact"
    NATIVE_LAYOUT_BACKED = "native_layout_backed"
    EXTERNAL_OCR_HIGH = "external_ocr_high"
    EXTERNAL_OCR_MEDIUM = "external_ocr_medium"
    EXTERNAL_OCR_LOW = "external_ocr_low"
    VISUAL_INTERPRETIVE = "visual_interpretive"


class ExtractionProvenance(NullVectorModel):
    """Normalized provenance for any acquired or enriched content unit."""

    source_track: SourceTrack
    producer_name: NonEmptyStr
    producer_version: NonEmptyStr | None = None
    confidence: float | None = None
    grounded_in_native_metadata: bool = False
    grounded_in_bbox: bool = False
    content_authoritativeness: ContentAuthoritativeness
    adapter_name: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_confidence(self) -> Self:
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            msg = "confidence must be between 0 and 1"
            raise ValueError(msg)
        return self


class GroundingEvidence(NullVectorModel):
    """Hard evidence that supports a block independently of provenance."""

    has_native_text_anchor: bool = False
    has_page_bbox_anchor: bool = False
    has_layout_anchor: bool = False
    supporting_native_refs: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


class DocumentEvent(NullVectorModel):
    """Typed document-level event suitable for artifact persistence and event buses."""

    event_id: NonEmptyStr
    event_name: NonEmptyStr
    severity: EventSeverity
    message: NonEmptyStr
    details: dict[str, ScalarValue] = Field(default_factory=dict)


class PageEvent(NullVectorModel):
    """Typed page-level event suitable for artifact persistence and event buses."""

    event_id: NonEmptyStr
    event_name: NonEmptyStr
    page_index: NonNegativeInt
    severity: EventSeverity
    message: NonEmptyStr
    details: dict[str, ScalarValue] = Field(default_factory=dict)


__all__ = [
    "ContentAuthoritativeness",
    "DocumentEvent",
    "EventSeverity",
    "ExtractionProvenance",
    "GroundingEvidence",
    "PageEvent",
    "SourceTrack",
    "TrustTier",
]
