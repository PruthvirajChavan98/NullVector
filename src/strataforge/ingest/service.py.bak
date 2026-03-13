"""Deterministic parser substrate orchestration."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import fitz
from pypdf import PdfReader
from pypdf import __version__ as pypdf_version

from strataforge.constants import CERTIFIED_PYMUPDF_VERSIONS, CERTIFIED_PYPDF_VERSIONS
from strataforge.domain.models import (
    DocumentFingerprint,
    OcrMode,
    PageExtractionMethod,
    PageLedgerRow,
    ParseRequest,
    ParserSettings,
    ParseRunIndex,
    ParseRunManifest,
)
from strataforge.ingest.artifacts import ArtifactStore, settings_digest
from strataforge.ingest.errors import (
    ExtractionFailureError,
    ParseConflictError,
    ParseSubstrateError,
)
from strataforge.ingest.fingerprint import fingerprint_document
from strataforge.ingest.ocr import (
    build_ocr_textpage,
    extract_ocr_rawdict,
    extract_ocr_text,
    validate_ocr_runtime,
)
from strataforge.ingest.outline import (
    extract_pymupdf_outlines,
    extract_pypdf_outlines,
    select_outline,
)
from strataforge.ingest.text import analyze_native_page, classify_ocr_need

fitz_module: Any = fitz


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _persist_native_rawdict(page_index: int, sample_every: int) -> bool:
    return page_index % sample_every == 0


class ParserSubstrateService:
    """Filesystem-backed deterministic PDF parser substrate."""

    def __init__(self) -> None:
        self._ocr_runtime_validated = False

    def parse(self, request: ParseRequest) -> ParseRunManifest:
        self._ocr_runtime_validated = False
        self._validate_parser_versions(request.settings)
        fingerprint = fingerprint_document(request.source_path)
        store = ArtifactStore(request.artifact_root, request.parse_run_id, fingerprint.document_id)
        digest = settings_digest(request.settings)
        run_index = store.load_run_index()
        if run_index is not None:
            if (
                run_index.document_id == fingerprint.document_id
                and run_index.fingerprint_sha256 == fingerprint.sha256
                and run_index.settings_digest == digest
            ):
                manifest = store.load_manifest_at(run_index.manifest_path)
                if manifest is None:
                    msg = "parse_run_id index points to a missing manifest"
                    raise ExtractionFailureError(msg, document_id=fingerprint.document_id)
                return manifest
            raise ParseConflictError(
                "parse_run_id already exists with different document, fingerprint, or settings",
                parse_run_id=request.parse_run_id,
                document_id=fingerprint.document_id,
            )

        store.ensure()
        source_copy_path = store.copy_source(request.source_path)
        store.write_json("source/fingerprint.json", fingerprint)

        try:
            with fitz_module.open(request.source_path) as document:
                reader = PdfReader(request.source_path)
                manifest = self._parse_document(
                    request=request,
                    fingerprint=fingerprint,
                    store=store,
                    source_copy_path=source_copy_path,
                    document=document,
                    reader=reader,
                    digest=digest,
                )
        except ParseSubstrateError:
            raise
        except Exception as exc:  # pragma: no cover - top-level safety net
            raise ExtractionFailureError(
                f"parse substrate failed: {exc}",
                document_id=fingerprint.document_id,
            ) from exc

        manifest_path = store.write_manifest(manifest)
        store.write_run_index(
            ParseRunIndex(
                parse_run_id=request.parse_run_id,
                document_id=fingerprint.document_id,
                fingerprint_sha256=fingerprint.sha256,
                settings_digest=digest,
                manifest_path=manifest_path,
            ),
        )
        return manifest

    def _parse_document(
        self,
        *,
        request: ParseRequest,
        fingerprint: DocumentFingerprint,
        store: ArtifactStore,
        source_copy_path: str,
        document: Any,
        reader: PdfReader,
        digest: str,
    ) -> ParseRunManifest:
        pymupdf_rich, pymupdf_entries = extract_pymupdf_outlines(document)
        pypdf_raw, pypdf_entries = extract_pypdf_outlines(reader)
        selected_source, selected_outline, outline_reports = select_outline(
            pymupdf_entries,
            pypdf_entries,
        )

        pymupdf_outline_path = store.write_json("outline/pymupdf.normalized.json", pymupdf_entries)
        pymupdf_rich_outline_path = store.write_json("outline/pymupdf.rich.json", pymupdf_rich)
        store.write_json("outline/pypdf.raw.json", pypdf_raw)
        pypdf_outline_path = store.write_json("outline/pypdf.normalized.json", pypdf_entries)
        store.write_json("outline/quality-report.json", outline_reports)
        selected_outline_path = store.write_json(
            "outline/selected.json",
            {
                "selected_source": selected_source,
                "entries": selected_outline,
            },
        )

        ledger_rows: list[PageLedgerRow] = []
        text_offset = 0
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            ledger_row = self._process_page(
                request=request,
                fingerprint=fingerprint,
                store=store,
                page=page,
                page_index=page_index,
                text_offset=text_offset,
            )
            ledger_rows.append(ledger_row)
            text_offset = ledger_row.text_offset_end

        ledger_path = store.write_ledger("ledger/page-ledger.jsonl", ledger_rows)
        return ParseRunManifest(
            parse_run_id=request.parse_run_id,
            document_id=fingerprint.document_id,
            artifact_root=str(store.base_path),
            fingerprint=fingerprint,
            settings=request.settings,
            settings_digest=digest,
            selected_outline_source=selected_source,
            outline_quality_reports=outline_reports,
            ledger_path=ledger_path,
            selected_outline_path=selected_outline_path,
            source_copy_path=source_copy_path,
            pymupdf_outline_path=pymupdf_outline_path,
            pymupdf_rich_outline_path=pymupdf_rich_outline_path,
            pypdf_outline_path=pypdf_outline_path,
            page_count=document.page_count,
        )

    def _process_page(
        self,
        *,
        request: ParseRequest,
        fingerprint: DocumentFingerprint,
        store: ArtifactStore,
        page: Any,
        page_index: int,
        text_offset: int,
    ) -> PageLedgerRow:
        native_analysis = analyze_native_page(page, request.settings)
        decision = classify_ocr_need(native_analysis, request.settings)
        page_dir = Path("pages") / f"{page_index:06d}"

        native_text_artifact_path = store.write_text(
            str(page_dir / "native.txt"),
            native_analysis.native_text,
        )
        native_rawdict_artifact_path: str | None = None
        if _persist_native_rawdict(
            page_index, request.settings.sample_native_rawdict_every_n_pages
        ):
            native_rawdict_artifact_path = store.write_json_gz(
                str(page_dir / "native.rawdict.json.gz"),
                native_analysis.native_rawdict,
            )

        text_artifact_path = native_text_artifact_path
        render_artifact_path: str | None = None
        ocr_text_artifact_path: str | None = None
        ocr_rawdict_artifact_path: str | None = None
        ocr_render_artifact_path: str | None = None
        extraction_method = (
            PageExtractionMethod.NATIVE_TEXT
            if native_analysis.native_char_count > 0
            else PageExtractionMethod.EMPTY
        )
        final_text = native_analysis.native_text

        if decision.needs_ocr:
            if not self._ocr_runtime_validated:
                validate_ocr_runtime(
                    request.settings,
                    document_id=fingerprint.document_id,
                    page_index=page_index,
                )
                self._ocr_runtime_validated = True
            pixmap = page.get_pixmap(dpi=request.settings.ocr_dpi)
            render_artifact_path = store.write_bytes(
                str(page_dir / "render.png"),
                pixmap.tobytes("png"),
            )
            ocr_render_artifact_path = render_artifact_path
            textpage = build_ocr_textpage(
                page,
                request.settings,
                ocr_mode=decision.ocr_mode,
                document_id=fingerprint.document_id,
                page_index=page_index,
            )
            final_text = extract_ocr_text(page, textpage)
            ocr_rawdict = extract_ocr_rawdict(page, textpage)
            ocr_text_artifact_path = store.write_text(str(page_dir / "ocr.txt"), final_text)
            ocr_rawdict_artifact_path = store.write_json_gz(
                str(page_dir / "ocr.rawdict.json.gz"),
                _json_safe(ocr_rawdict),
            )
            text_artifact_path = ocr_text_artifact_path
            if decision.ocr_mode == OcrMode.NONE:  # pragma: no cover - defensive impossible state
                extraction_method = PageExtractionMethod.EMPTY
            elif decision.ocr_mode == OcrMode.PARTIAL and native_analysis.native_char_count > 0:
                extraction_method = PageExtractionMethod.MIXED
            else:
                extraction_method = PageExtractionMethod.OCR

        final_text_sha256 = _hash_text(final_text)
        text_length = len(final_text)
        return PageLedgerRow(
            document_id=fingerprint.document_id,
            parse_run_id=request.parse_run_id,
            source_path=request.source_path,
            page_index=page_index,
            page_label=page.get_label(),
            extraction_method=extraction_method,
            needs_ocr=decision.needs_ocr,
            native_text_available=native_analysis.native_char_count > 0,
            ocr_mode=decision.ocr_mode,
            ocr_reason_codes=tuple(decision.reason_codes),
            text_offset_start=text_offset,
            text_offset_end=text_offset + text_length,
            text_length=text_length,
            text_sha256=final_text_sha256,
            native_text_sha256=native_analysis.native_text_sha256,
            native_word_count=native_analysis.native_word_count,
            native_char_count=native_analysis.native_char_count,
            image_coverage_ratio=native_analysis.image_coverage_ratio,
            vector_path_count=native_analysis.vector_path_count,
            dense_small_vector_count=native_analysis.dense_small_vector_count,
            render_artifact_path=render_artifact_path,
            text_artifact_path=text_artifact_path,
            native_text_artifact_path=native_text_artifact_path,
            native_rawdict_artifact_path=native_rawdict_artifact_path,
            ocr_text_artifact_path=ocr_text_artifact_path,
            ocr_rawdict_artifact_path=ocr_rawdict_artifact_path,
            ocr_render_artifact_path=ocr_render_artifact_path,
        )

    def _validate_parser_versions(self, settings: ParserSettings) -> None:
        if settings.pymupdf_version not in CERTIFIED_PYMUPDF_VERSIONS:
            msg = (
                f"configured PyMuPDF version {settings.pymupdf_version} is not in the certified "
                f"set {CERTIFIED_PYMUPDF_VERSIONS}"
            )
            raise ExtractionFailureError(msg, document_id="unknown")
        if settings.pypdf_version not in CERTIFIED_PYPDF_VERSIONS:
            msg = (
                f"configured pypdf version {settings.pypdf_version} is not in the certified set "
                f"{CERTIFIED_PYPDF_VERSIONS}"
            )
            raise ExtractionFailureError(msg, document_id="unknown")
        if fitz.VersionBind not in CERTIFIED_PYMUPDF_VERSIONS:
            msg = (
                f"installed PyMuPDF version {fitz.VersionBind} is outside the certified set "
                f"{CERTIFIED_PYMUPDF_VERSIONS}"
            )
            raise ExtractionFailureError(msg, document_id="unknown")
        if pypdf_version not in CERTIFIED_PYPDF_VERSIONS:
            msg = (
                f"installed pypdf version {pypdf_version} is outside the certified set "
                f"{CERTIFIED_PYPDF_VERSIONS}"
            )
            raise ExtractionFailureError(msg, document_id="unknown")
        if fitz.VersionBind != settings.pymupdf_version:
            msg = (
                f"configured PyMuPDF version {settings.pymupdf_version} "
                f"does not match installed {fitz.VersionBind}"
            )
            raise ExtractionFailureError(
                msg,
                document_id="unknown",
            )
        if pypdf_version != settings.pypdf_version:
            msg = (
                f"configured pypdf version {settings.pypdf_version} "
                f"does not match installed {pypdf_version}"
            )
            raise ExtractionFailureError(
                msg,
                document_id="unknown",
            )


def parse_document(request: ParseRequest) -> ParseRunManifest:
    """Parse a document through the deterministic substrate."""

    return ParserSubstrateService().parse(request)
