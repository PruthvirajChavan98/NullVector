"""Framework-owned Markdown-native acquisition provider."""

from __future__ import annotations

from pathlib import Path

from nullvector._text import normalized_text_key
from nullvector.domain.common import BoundingBox
from nullvector.domain.events import (
    ContentAuthoritativeness,
    DocumentEvent,
    EventSeverity,
    ExtractionProvenance,
    SourceTrack,
)
from nullvector.domain.ledger import (
    AcquisitionManifest,
    AcquisitionRequest,
    CanonicalDocumentLedger,
    CanonicalPage,
    DocumentFingerprint,
    LineBlock,
    SourceMetadata,
)
from nullvector.ingest._markdown import (
    parse_markdown_source,
    synthetic_heading_font_size,
    synthetic_line_top_y,
)
from nullvector.storage._serialization import settings_digest


def _line_provenance() -> ExtractionProvenance:
    return ExtractionProvenance(
        source_track=SourceTrack.NATIVE,
        producer_name="markdown_native",
        grounded_in_native_metadata=True,
        grounded_in_bbox=False,
        content_authoritativeness=ContentAuthoritativeness.AUTHORITATIVE,
    )


class MarkdownNativeAcquisitionProvider:
    """Deterministic Markdown acquisition provider for authored UTF-8 Markdown."""

    provider_identity = "markdown_native"

    def __init__(
        self,
        *,
        source_fingerprint: DocumentFingerprint | None = None,
    ) -> None:
        self._source_fingerprint = source_fingerprint

    def acquire(self, request: AcquisitionRequest) -> CanonicalDocumentLedger:
        if self._source_fingerprint is None:
            msg = "markdown acquisition provider requires a precomputed source fingerprint"
            raise ValueError(msg)
        fingerprint = self._source_fingerprint
        source = Path(request.source_path)
        parsed = parse_markdown_source(
            request.source_path,
            settings=request.settings.markdown,
        )

        pages: list[CanonicalPage] = []
        for page in parsed.pages:
            blocks: list[LineBlock] = []
            occurrence_counts: dict[str, int] = {}
            for reading_index, line in enumerate(page.lines):
                top_y = synthetic_line_top_y(reading_index)
                font_size = synthetic_heading_font_size(line.heading_level)
                line_height = 12.0 if line.heading_level is None else font_size
                width = float(max(len(line.content), 1) * 7)
                normalized = normalized_text_key(line.content)
                occurrence_index = occurrence_counts.get(normalized, 0)
                occurrence_counts[normalized] = occurrence_index + 1
                blocks.append(
                    LineBlock(
                        line_id=f"page-{page.page_index}-line-{reading_index:04d}",
                        bbox=BoundingBox(
                            x0=0.0,
                            y0=top_y,
                            x1=width,
                            y1=top_y + line_height,
                        ),
                        content=line.content,
                        reading_index=reading_index,
                        occurrence_index=occurrence_index,
                        top_y=top_y,
                        font_size=font_size,
                        font_family_hint=(
                            f"MarkdownHeading{line.heading_level}"
                            if line.heading_level is not None
                            else "MarkdownBody"
                        ),
                        provenance=_line_provenance(),
                    )
                )
            page_height = max(792.0, len(blocks) * 14.0 + 36.0)
            pages.append(
                CanonicalPage(
                    page_index=page.page_index,
                    page_label=str(page.page_index + 1),
                    width=612.0,
                    height=page_height,
                    native_available=True,
                    blocks=tuple(blocks),
                    events=(),
                )
            )

        source_metadata = SourceMetadata(
            source_path=str(source.resolve()),
            file_size_bytes=source.stat().st_size,
            mime_type="text/markdown",
            page_count=fingerprint.page_count,
            extra={"source_kind": request.source_kind.value},
        )
        acquisition_manifest = AcquisitionManifest(
            source_fingerprint_sha256=fingerprint.sha256,
            settings_digest=settings_digest(request.settings),
            acquisition_provider_identity=self.provider_identity,
        )
        document_events = (
            DocumentEvent(
                event_id=f"{fingerprint.document_id}-acquisition-markdown",
                event_name="markdown_acquisition_completed",
                severity=EventSeverity.INFO,
                message="markdown-native acquisition completed",
                details={
                    "provider_identity": self.provider_identity,
                    "page_count": fingerprint.page_count,
                },
            ),
        )
        return CanonicalDocumentLedger(
            document_id=fingerprint.document_id,
            source_fingerprint=fingerprint,
            source_metadata=source_metadata,
            acquisition_manifest=acquisition_manifest,
            pages=tuple(pages),
            document_events=document_events,
        )
