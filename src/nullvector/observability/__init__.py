"""Typed observability bus and built-in subscribers."""

from nullvector.observability.bus import EventBus
from nullvector.observability.events import (
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
from nullvector.observability.subscriber import EventSubscriber
from nullvector.observability.subscribers import (
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
