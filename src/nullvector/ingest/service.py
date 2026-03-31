"""Deterministic parser substrate orchestration."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

from pypdf import PdfReader

from nullvector.constants import DEFAULT_ARTIFACT_ROOT
from nullvector.domain.ledger import (
    DocumentFingerprint,
    OcrMode,
    PageExtractionMethod,
    PageLedgerRow,
    ParseRequest,
    ParseRunManifest,
)
from nullvector.ingest.errors import (
    ExtractionFailureError,
    ParseConflictError,
    ParseSubstrateError,
)
from nullvector.ingest.fingerprint import fingerprint_document
from nullvector.ingest.ocr import (
    build_ocr_textpage,
    extract_ocr_rawdict,
    extract_ocr_text,
    validate_ocr_runtime,
)
from nullvector.ingest.outline import (
    extract_pymupdf_outlines,
    extract_pypdf_outlines,
    select_outline,
)
from nullvector.ingest.pdf_backend import open_document
from nullvector.ingest.text import analyze_native_page, classify_ocr_need
from nullvector.runtime_validation import validate_pdf_runtime_versions
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage._serialization import (
    canonical_json_text,
    json_safe,
    run_identity_matches,
    settings_digest,
)
from nullvector.storage.protocol import RunScopedStore


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _persist_native_rawdict(page_index: int, sample_every: int) -> bool:
    return page_index % sample_every == 0


class ParserSubstrateService:
    """Storage-backed deterministic PDF parser substrate."""

    def __init__(self, *, storage: StorageConfig | None = None) -> None:
        self._ocr_runtime_validated = False
        self._storage = storage

    def parse(self, request: ParseRequest) -> ParseRunManifest:
        self._ocr_runtime_validated = False
        validate_pdf_runtime_versions(
            configured_pymupdf_version=request.settings.pymupdf_version,
            configured_pypdf_version=request.settings.pypdf_version,
        )
        fingerprint = fingerprint_document(request.source_path)
        digest = settings_digest(request.settings)
        configured_artifact_root = str(
            Path(request.artifact_root or DEFAULT_ARTIFACT_ROOT)
            / request.parse_run_id
            / fingerprint.document_id
        )
        store = build_document_store(
            self._storage,
            default_filesystem_root=configured_artifact_root,
        )
        artifact_root = store.resolve_artifact_root(
            run_type="parse",
            run_id=request.parse_run_id,
            document_id=fingerprint.document_id,
            configured_root=configured_artifact_root,
        )
        store.register_document(fingerprint)
        expected_identity = {
            "document_id": fingerprint.document_id,
            "fingerprint_sha256": fingerprint.sha256,
            "settings_digest": digest,
        }
        created, run_record = store.reserve_run(
            run_type="parse",
            run_id=request.parse_run_id,
            document_id=fingerprint.document_id,
            artifact_root=artifact_root,
            identity=expected_identity,
        )
        run_store = store.for_run(
            run_type="parse",
            run_id=request.parse_run_id,
            document_id=fingerprint.document_id,
        )
        if not created:
            if run_identity_matches(run_record, expected_identity):
                manifest_ref = cast(
                    str | None,
                    run_record.get("manifest_ref") or run_record.get("manifest_path"),
                )
                if manifest_ref is None:
                    msg = "parse_run_id index points to a missing manifest"
                    raise ExtractionFailureError(msg, document_id=fingerprint.document_id)
                return ParseRunManifest.model_validate_json(
                    canonical_json_text(store.read_json_artifact(manifest_ref))
                )
            raise ParseConflictError(
                "parse_run_id already exists with different document, fingerprint, or settings",
                parse_run_id=request.parse_run_id,
                document_id=fingerprint.document_id,
            )

        source_copy_path = run_store.put_binary(
            asset_path="source/original.pdf",
            content_type="application/pdf",
            data=Path(request.source_path).read_bytes(),
        )
        run_store.put_json(
            artifact_kind="fingerprint",
            artifact_path="source/fingerprint.json",
            payload=fingerprint,
        )

        try:
            with open_document(request.source_path) as document:
                reader = PdfReader(request.source_path)
                manifest = self._parse_document(
                    request=request,
                    fingerprint=fingerprint,
                    store=run_store,
                    source_copy_path=source_copy_path,
                    document=document,
                    reader=reader,
                    digest=digest,
                    artifact_root=artifact_root,
                )
        except ParseSubstrateError:
            raise
        except Exception as exc:  # pragma: no cover - top-level safety net
            raise ExtractionFailureError(
                f"parse substrate failed: {exc}",
                document_id=fingerprint.document_id,
            ) from exc

        manifest_path = run_store.put_json(
            artifact_kind="manifest",
            artifact_path="manifest.json",
            payload=manifest,
        )
        run_store.complete(
            manifest_ref=manifest_path,
            manifest=manifest,
        )
        return manifest

    def _parse_document(
        self,
        *,
        request: ParseRequest,
        fingerprint: DocumentFingerprint,
        store: RunScopedStore,
        source_copy_path: str,
        document: Any,
        reader: PdfReader,
        digest: str,
        artifact_root: str | None,
    ) -> ParseRunManifest:
        pymupdf_rich, pymupdf_entries = extract_pymupdf_outlines(document)
        pypdf_raw, pypdf_entries = extract_pypdf_outlines(reader)
        selected_source, selected_outline, outline_reports = select_outline(
            pymupdf_entries,
            pypdf_entries,
        )

        pymupdf_outline_path = store.put_json(
            artifact_kind="outline",
            artifact_path="outline/pymupdf.normalized.json",
            payload=pymupdf_entries,
        )
        pymupdf_rich_outline_path = store.put_json(
            artifact_kind="outline",
            artifact_path="outline/pymupdf.rich.json",
            payload=pymupdf_rich,
        )
        store.put_json(
            artifact_kind="outline",
            artifact_path="outline/pypdf.raw.json",
            payload=pypdf_raw,
        )
        pypdf_outline_path = store.put_json(
            artifact_kind="outline",
            artifact_path="outline/pypdf.normalized.json",
            payload=pypdf_entries,
        )
        store.put_json(
            artifact_kind="outline",
            artifact_path="outline/quality-report.json",
            payload=outline_reports,
        )
        selected_outline_path = store.put_json(
            artifact_kind="outline",
            artifact_path="outline/selected.json",
            payload={
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

        ledger_path = store.put_jsonl(
            artifact_kind="ledger",
            artifact_path="ledger/page-ledger.jsonl",
            payloads=tuple(ledger_rows),
        )
        return ParseRunManifest(
            parse_run_id=request.parse_run_id,
            document_id=fingerprint.document_id,
            artifact_root=artifact_root,
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
        store: RunScopedStore,
        page: Any,
        page_index: int,
        text_offset: int,
    ) -> PageLedgerRow:
        native_analysis = analyze_native_page(page, request.settings)
        decision = classify_ocr_need(native_analysis, request.settings)
        page_dir = Path("pages") / f"{page_index:06d}"

        native_text_artifact_path = store.put_text(
            artifact_kind="page_text",
            artifact_path=str(page_dir / "native.txt"),
            content=native_analysis.native_text,
        )
        native_rawdict_artifact_path: str | None = None
        if _persist_native_rawdict(
            page_index, request.settings.sample_native_rawdict_every_n_pages
        ):
            native_rawdict_artifact_path = store.put_json(
                artifact_kind="page_rawdict",
                artifact_path=str(page_dir / "native.rawdict.json.gz"),
                payload=native_analysis.native_rawdict,
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
            render_artifact_path = store.put_binary(
                asset_path=str(page_dir / "render.png"),
                content_type="image/png",
                data=pixmap.tobytes("png"),
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
            ocr_text_artifact_path = store.put_text(
                artifact_kind="page_text",
                artifact_path=str(page_dir / "ocr.txt"),
                content=final_text,
            )
            ocr_rawdict_artifact_path = store.put_json(
                artifact_kind="page_rawdict",
                artifact_path=str(page_dir / "ocr.rawdict.json.gz"),
                payload=json_safe(ocr_rawdict),
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


def parse_document(
    request: ParseRequest,
    *,
    storage: StorageConfig | None = None,
) -> ParseRunManifest:
    """Parse a document through the deterministic substrate."""

    return ParserSubstrateService(storage=storage).parse(request)
