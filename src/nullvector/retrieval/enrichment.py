"""Cached visual enrichment helpers for retrieval units."""

from __future__ import annotations

from nullvector.domain.retrieval import RetrievalCorpus, RetrievalEvidence, RetrievalUnitType
from nullvector.domain.tree import VisualEnrichmentAttachment


class VisualAttachmentIndex:
    """Fast region-id lookup over cached visual enrichment attachments."""

    def __init__(self, attachments: tuple[VisualEnrichmentAttachment, ...]) -> None:
        self._attachments_by_region = {
            attachment.region_id: attachment for attachment in attachments
        }

    def get_for_region(self, region_id: str) -> VisualEnrichmentAttachment | None:
        return self._attachments_by_region.get(region_id)

    def augment_unit(self, unit: RetrievalEvidence) -> RetrievalEvidence:
        if unit.unit_type not in {
            RetrievalUnitType.VISUAL,
            RetrievalUnitType.UNRESOLVED_VISUAL,
        }:
            return unit
        if unit.visual_region is None:
            return unit
        attachment = self.get_for_region(unit.visual_region.region_id)
        if attachment is None:
            return unit
        keywords = tuple(label for label in attachment.insight.labels if label)
        metadata = dict(unit.metadata)
        metadata.update(
            {
                "attachment_id": attachment.attachment_id,
                "attachment_audit_path": attachment.audit_path,
                "attachment_attributes": dict(attachment.insight.attributes),
                "attachment_confidence": attachment.confidence,
            }
        )
        return unit.model_copy(
            update={
                "text": attachment.insight.summary,
                "keywords": keywords or unit.keywords,
                "interpretive": True,
                "metadata": metadata,
            }
        )


def augment_corpus_with_attachments(
    *,
    corpus: RetrievalCorpus,
    attachments: tuple[VisualEnrichmentAttachment, ...],
) -> RetrievalCorpus:
    """Return a corpus copy with cached visual attachments folded into visual units."""

    index = VisualAttachmentIndex(attachments)
    return corpus.model_copy(
        update={"units": tuple(index.augment_unit(unit) for unit in corpus.units)}
    )


__all__ = [
    "VisualAttachmentIndex",
    "augment_corpus_with_attachments",
]
