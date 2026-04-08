"""Framework-owned native PyMuPDF acquisition provider (VLM-backed)."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.events import (
    ContentAuthoritativeness,
    DocumentEvent,
    EventSeverity,
    ExtractionProvenance,
    GroundingEvidence,
    SourceTrack,
)
from nullvector.domain.ledger import (
    AcquisitionManifest,
    AcquisitionRequest,
    CanonicalDocumentLedger,
    CanonicalPage,
    DocumentFingerprint,
    SourceMetadata,
    TextBlock,
)
from nullvector.ingest.page_renderer import open_pdf
from nullvector.ingest.vlm_transcriber import PageTranscription, VLMPageTranscriber
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.storage._serialization import settings_digest


def _page_from_transcription(transcription: PageTranscription, document_id: str) -> CanonicalPage:
    """Build a CanonicalPage from a VLM transcription result."""

    block = TextBlock(
        block_type="text_block",
        block_id=f"{document_id}-p{transcription.page_index:06d}-vlm",
        bbox=None,
        content=transcription.markdown_text,
        reading_index=0,
        family_reading_index=0,
        line_count=transcription.markdown_text.count("\n") + 1,
        word_count=len(transcription.markdown_text.split()),
        provenance=ExtractionProvenance(
            source_track=SourceTrack.VISUAL_ENRICHMENT,
            producer_name="vlm_transcriber",
            content_authoritativeness=ContentAuthoritativeness.INTERPRETIVE,
        ),
        grounding=GroundingEvidence(),
    )
    return CanonicalPage(
        page_index=transcription.page_index,
        width=1.0,
        height=1.0,
        native_available=False,
        blocks=(block,),
    )


def _page_from_raw_text(
    page_index: int,
    text: str,
    document_id: str,
) -> CanonicalPage:
    """Build a CanonicalPage from raw PyMuPDF text extraction (no-VLM fallback)."""

    block = TextBlock(
        block_type="text_block",
        block_id=f"{document_id}-p{page_index:06d}-native",
        bbox=None,
        content=text if text.strip() else "(empty page)",
        reading_index=0,
        family_reading_index=0,
        line_count=text.count("\n") + 1,
        word_count=len(text.split()),
        provenance=ExtractionProvenance(
            source_track=SourceTrack.NATIVE,
            producer_name="native_pymupdf",
            content_authoritativeness=ContentAuthoritativeness.AUTHORITATIVE,
            grounded_in_native_metadata=True,
        ),
        grounding=GroundingEvidence(
            has_native_text_anchor=True,
        ),
    )
    return CanonicalPage(
        page_index=page_index,
        width=1.0,
        height=1.0,
        native_available=True,
        blocks=(block,),
    )


class NativePyMuPDFAcquisitionProvider:
    """Native acquisition provider that renders pages and optionally invokes a VLM."""

    provider_identity = "native_pymupdf"

    def __init__(
        self,
        *,
        source_fingerprint: DocumentFingerprint | None = None,
        gateway: StructuredLLMGateway | None = None,
    ) -> None:
        self._source_fingerprint = source_fingerprint
        self._gateway = gateway

    def acquire(self, request: AcquisitionRequest) -> CanonicalDocumentLedger:
        if self._source_fingerprint is None:
            msg = "native acquisition provider requires a precomputed source fingerprint"
            raise ValueError(msg)
        fingerprint = self._source_fingerprint
        source = Path(request.source_path)

        if self._gateway is not None:
            transcriber = VLMPageTranscriber(self._gateway, dpi=request.settings.render_dpi)
            transcriptions = transcriber.transcribe_document(
                str(source),
                document_id=fingerprint.document_id,
            )
            pages = tuple(
                _page_from_transcription(t, fingerprint.document_id) for t in transcriptions
            )
        else:
            # Fallback: extract raw text from PyMuPDF without VLM
            with open_pdf(str(source)) as document:
                pages = tuple(
                    _page_from_raw_text(
                        page_index=page_index,
                        text=document.load_page(page_index).get_text(),
                        document_id=fingerprint.document_id,
                    )
                    for page_index in range(document.page_count)
                )

        source_metadata = SourceMetadata(
            source_path=str(source.resolve()),
            file_size_bytes=source.stat().st_size,
            mime_type="application/pdf",
            page_count=fingerprint.page_count,
        )
        acquisition_manifest = AcquisitionManifest(
            source_fingerprint_sha256=fingerprint.sha256,
            settings_digest=settings_digest(request.settings),
            acquisition_provider_identity=self.provider_identity,
        )
        document_events = (
            DocumentEvent(
                event_id=f"{fingerprint.document_id}-acquisition-native",
                event_name="native_acquisition_completed",
                severity=EventSeverity.INFO,
                message=(
                    "VLM-backed acquisition completed"
                    if self._gateway is not None
                    else "native text extraction completed (no VLM)"
                ),
                details={
                    "provider_identity": self.provider_identity,
                    "page_count": fingerprint.page_count,
                    "vlm_enabled": self._gateway is not None,
                },
            ),
        )
        return CanonicalDocumentLedger(
            document_id=fingerprint.document_id,
            source_fingerprint=fingerprint,
            source_metadata=source_metadata,
            acquisition_manifest=acquisition_manifest,
            pages=pages,
            document_events=document_events,
        )
