"""Framework-owned native PyMuPDF acquisition provider."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from nullvector.domain.events import DocumentEvent, EventSeverity
from nullvector.domain.ledger import (
    AcquisitionManifest,
    AcquisitionRequest,
    CanonicalDocumentLedger,
    SourceMetadata,
)
from nullvector.ingest.fingerprint import fingerprint_document
from nullvector.ingest.outline import (
    extract_pymupdf_outlines,
    extract_pypdf_outlines,
    select_outline,
)
from nullvector.ingest.pdf_backend import open_document
from nullvector.ingest.profiling import profile_page
from nullvector.storage._serialization import settings_digest


class NativePyMuPDFAcquisitionProvider:
    """Native-first acquisition provider that never invokes OCR or external services."""

    provider_identity = "native_pymupdf"

    def acquire(self, request: AcquisitionRequest) -> CanonicalDocumentLedger:
        fingerprint = fingerprint_document(
            request.source_path,
            source_kind=request.source_kind,
            acquisition_settings=request.settings,
        )
        source = Path(request.source_path)

        with open_document(request.source_path) as document:
            reader = PdfReader(request.source_path)
            _, pymupdf_entries = extract_pymupdf_outlines(document)
            _, pypdf_entries = extract_pypdf_outlines(reader)
            selected_source, selected_entries, outline_reports = select_outline(
                pymupdf_entries, pypdf_entries
            )

            pages = []
            for page_index in range(document.page_count):
                profiled = profile_page(
                    document_id=fingerprint.document_id,
                    page_index=page_index,
                    page=document.load_page(page_index),
                    detect_tables=request.settings.detect_tables,
                    table_min_columns=request.settings.table_min_columns,
                    table_min_rows=request.settings.table_min_rows,
                    dense_vector_threshold=request.settings.dense_vector_threshold,
                    small_vector_max_area_ratio=request.settings.small_vector_max_area_ratio,
                    vector_scan_limit=request.settings.vector_scan_limit,
                )
                pages.append(profiled.page)

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
            selected_outline_source=selected_source,
            outline_quality_reports=outline_reports,
            selected_outline_entries=tuple(selected_entries),
        )
        document_events = (
            DocumentEvent(
                event_id=f"{fingerprint.document_id}-acquisition-native",
                event_name="native_acquisition_completed",
                severity=EventSeverity.INFO,
                message="native PyMuPDF acquisition completed",
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
