"""Typed observability bus and built-in subscribers."""

from strataforge.observability.bus import EventBus
from strataforge.observability.events import (
    AcquisitionStarted,
    ExportCompleted,
    ExternalEnrichmentMerged,
    ExternalEnrichmentRequested,
    FrameworkEvent,
    HierarchyStrategySelected,
    NodeCommitted,
    NodeSummarized,
    NodeVerificationFailed,
    PageNativeParsed,
    PageProfiled,
    ProjectionCreated,
    SourceFingerprintComputed,
    UnresolvedRegionEmitted,
    VisualEnrichmentAttached,
)
from strataforge.observability.subscriber import EventSubscriber
from strataforge.observability.subscribers import (
    JsonLoggerSubscriber,
    RichProgressSubscriber,
)

__all__ = [
    "AcquisitionStarted",
    "EventBus",
    "EventSubscriber",
    "ExportCompleted",
    "ExternalEnrichmentMerged",
    "ExternalEnrichmentRequested",
    "FrameworkEvent",
    "HierarchyStrategySelected",
    "JsonLoggerSubscriber",
    "NodeCommitted",
    "NodeSummarized",
    "NodeVerificationFailed",
    "PageNativeParsed",
    "PageProfiled",
    "ProjectionCreated",
    "RichProgressSubscriber",
    "SourceFingerprintComputed",
    "UnresolvedRegionEmitted",
    "VisualEnrichmentAttached",
]
