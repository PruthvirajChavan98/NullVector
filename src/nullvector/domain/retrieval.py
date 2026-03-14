"""Typed retrieval corpus, planning, and answer-citation contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, NonNegativeInt, model_validator

from nullvector.domain.common import ContentSpan, NonEmptyStr, PageSpan, StrataModel
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


class RetrievalEvidence(StrataModel):
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


class RetrievalCorpus(StrataModel):
    """Document-scoped retrieval corpus persisted as an artifact."""

    document_id: NonEmptyStr
    units: tuple[RetrievalEvidence, ...] = Field(default_factory=tuple)


class RetrievalManifest(StrataModel):
    """Manifest for a persisted retrieval corpus artifact set."""

    document_id: NonEmptyStr
    artifact_root: NonEmptyStr
    corpus_path: NonEmptyStr
    stats_path: NonEmptyStr
    unit_count: NonNegativeInt


class QueryPlan(StrataModel):
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


class RetrievalHit(StrataModel):
    """Scored retrieval match with deterministic scoring details."""

    unit: RetrievalEvidence
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    matched_terms: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


class AnswerCitation(StrataModel):
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
    "QueryPlan",
    "RetrievalCorpus",
    "RetrievalEvidence",
    "RetrievalHit",
    "RetrievalManifest",
    "RetrievalModality",
    "RetrievalUnitType",
]
