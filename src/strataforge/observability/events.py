"""Typed runtime events emitted across acquisition, synthesis, and export flows."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, NonNegativeInt

from nullvector.domain.common import NonEmptyStr, StrataModel


class FrameworkEvent(StrataModel):
    """Base typed event emitted by the framework event bus."""

    event_id: NonEmptyStr
    event_name: NonEmptyStr
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    document_id: NonEmptyStr


class SourceFingerprintComputed(FrameworkEvent):
    source_path: NonEmptyStr
    sha256: NonEmptyStr


class AcquisitionStarted(FrameworkEvent):
    acquisition_run_id: NonEmptyStr
    provider_identity: NonEmptyStr


class PageNativeParsed(FrameworkEvent):
    page_index: NonNegativeInt
    block_count: NonNegativeInt


class PageProfiled(FrameworkEvent):
    page_index: NonNegativeInt
    unresolved_region_count: NonNegativeInt


class UnresolvedRegionEmitted(FrameworkEvent):
    page_index: NonNegativeInt
    region_id: NonEmptyStr
    reason_code: NonEmptyStr


class ExternalEnrichmentRequested(FrameworkEvent):
    request_id: NonEmptyStr
    region_id: NonEmptyStr
    node_id: NonEmptyStr | None = None


class ExternalEnrichmentMerged(FrameworkEvent):
    attachment_id: NonEmptyStr
    region_id: NonEmptyStr
    node_id: NonEmptyStr | None = None


class ProjectionCreated(FrameworkEvent):
    page_count: NonNegativeInt
    projection_path: NonEmptyStr


class HierarchyStrategySelected(FrameworkEvent):
    tree_run_id: NonEmptyStr
    strategy: NonEmptyStr


class NodeCommitted(FrameworkEvent):
    tree_run_id: NonEmptyStr
    node_id: NonEmptyStr
    title: NonEmptyStr


class NodeVerificationFailed(FrameworkEvent):
    tree_run_id: NonEmptyStr
    subject_id: NonEmptyStr
    issue_count: NonNegativeInt


class NodeSummarized(FrameworkEvent):
    node_id: NonEmptyStr
    summary_method: NonEmptyStr


class VisualEnrichmentAttached(FrameworkEvent):
    attachment_id: NonEmptyStr
    region_id: NonEmptyStr
    node_id: NonEmptyStr | None = None


class ExportCompleted(FrameworkEvent):
    exporter_name: NonEmptyStr
    item_count: NonNegativeInt


__all__ = [
    "AcquisitionStarted",
    "ExportCompleted",
    "ExternalEnrichmentMerged",
    "ExternalEnrichmentRequested",
    "FrameworkEvent",
    "HierarchyStrategySelected",
    "NodeCommitted",
    "NodeSummarized",
    "NodeVerificationFailed",
    "PageNativeParsed",
    "PageProfiled",
    "ProjectionCreated",
    "SourceFingerprintComputed",
    "UnresolvedRegionEmitted",
    "VisualEnrichmentAttached",
]
