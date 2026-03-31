"""Parallel v2 acquisition + projection orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from logging import Logger
from pathlib import Path
from typing import Any, cast

from pypdf import PdfReader

from nullvector.constants import DEFAULT_ACQUISITION_ARTIFACT_ROOT
from nullvector.domain.common import BatchItemFailure, BatchResult
from nullvector.domain.ledger import (
    AcquisitionRequest,
    AcquisitionRunManifest,
    DocumentFingerprint,
    OutlineEntry,
    OutlineQualityReport,
    OutlineSource,
    SourceDocumentKind,
    UnresolvedRegion,
)
from nullvector.ingest._markdown import parse_markdown_source
from nullvector.ingest.errors import (
    ExtractionFailureError,
    ParseConflictError,
    ParseSubstrateError,
)
from nullvector.ingest.fingerprint import fingerprint_document
from nullvector.ingest.outline import (
    extract_pymupdf_outlines,
    extract_pypdf_outlines,
    score_outline,
    select_outline,
)
from nullvector.ingest.pdf_backend import open_document
from nullvector.ingest.projection import (
    build_canonical_text_substrate,
    project_ledger_to_tree_synthesis_view,
)
from nullvector.ingest.protocols import AcquisitionProvider
from nullvector.ingest.providers.markdown_native import MarkdownNativeAcquisitionProvider
from nullvector.ingest.providers.native_pymupdf import NativePyMuPDFAcquisitionProvider
from nullvector.ingest.visual_assets import materialize_visual_assets
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.runtime_validation import validate_pdf_runtime_versions
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage._serialization import (
    canonical_json_text,
    run_identity_matches,
    settings_digest,
)


def _default_provider(
    request: AcquisitionRequest,
    *,
    source_fingerprint: DocumentFingerprint,
) -> AcquisitionProvider:
    if (
        request.source_kind is SourceDocumentKind.PDF
        and request.provider_identity == "native_pymupdf"
    ):
        return NativePyMuPDFAcquisitionProvider(source_fingerprint=source_fingerprint)
    if (
        request.source_kind is SourceDocumentKind.MARKDOWN
        and request.provider_identity == "markdown_native"
    ):
        return MarkdownNativeAcquisitionProvider(source_fingerprint=source_fingerprint)
    msg = f"unsupported acquisition provider identity: {request.provider_identity}"
    raise ExtractionFailureError(msg, document_id="unknown")


def _validate_request_provider(request: AcquisitionRequest) -> None:
    expected_provider = (
        "native_pymupdf" if request.source_kind is SourceDocumentKind.PDF else "markdown_native"
    )
    if request.provider_identity != expected_provider:
        msg = (
            f"source_kind {request.source_kind.value!r} requires provider_identity "
            f"{expected_provider!r}"
        )
        raise ExtractionFailureError(msg, document_id="unknown")


def _source_copy_metadata(request: AcquisitionRequest) -> tuple[str, str]:
    if request.source_kind is SourceDocumentKind.MARKDOWN:
        return ("source/original.md", "text/markdown")
    return ("source/original.pdf", "application/pdf")


class AcquisitionService:
    """Storage-backed deterministic acquisition + projection runtime."""

    def __init__(
        self,
        provider: AcquisitionProvider | None = None,
        *,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._provider = provider
        self._logger = resolve_runtime_logger(logger)
        self._storage = storage

    def acquire(self, request: AcquisitionRequest) -> AcquisitionRunManifest:
        _validate_request_provider(request)
        if request.source_kind is SourceDocumentKind.PDF:
            validate_pdf_runtime_versions(
                configured_pymupdf_version=request.settings.pymupdf_version,
                configured_pypdf_version=request.settings.pypdf_version,
            )
        fingerprint = fingerprint_document(
            request.source_path,
            source_kind=request.source_kind,
            acquisition_settings=request.settings,
        )
        log_event(
            self._logger,
            "SourceFingerprintComputed",
            document_id=fingerprint.document_id,
            source_path=fingerprint.source_path,
            sha256=fingerprint.sha256,
        )
        log_event(
            self._logger,
            "AcquisitionStarted",
            document_id=fingerprint.document_id,
            acquisition_run_id=request.acquisition_run_id,
            provider_identity=request.provider_identity,
        )
        digest = settings_digest(request.settings)
        configured_artifact_root = str(
            Path(request.artifact_root or DEFAULT_ACQUISITION_ARTIFACT_ROOT)
            / request.acquisition_run_id
            / fingerprint.document_id
        )
        store = build_document_store(
            self._storage,
            default_filesystem_root=configured_artifact_root,
        )
        artifact_root = store.resolve_artifact_root(
            run_type="acquisition",
            run_id=request.acquisition_run_id,
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
            run_type="acquisition",
            run_id=request.acquisition_run_id,
            document_id=fingerprint.document_id,
            artifact_root=artifact_root,
            identity=expected_identity,
        )
        run_store = store.for_run(
            run_type="acquisition",
            run_id=request.acquisition_run_id,
            document_id=fingerprint.document_id,
        )
        if not created:
            if run_identity_matches(run_record, expected_identity):
                manifest_ref = cast(
                    str | None,
                    run_record.get("manifest_ref") or run_record.get("manifest_path"),
                )
                if manifest_ref is None:
                    msg = "acquisition_run_id index points to a missing manifest"
                    raise ExtractionFailureError(msg, document_id=fingerprint.document_id)
                return AcquisitionRunManifest.model_validate_json(
                    canonical_json_text(store.read_json_artifact(manifest_ref))
                )
            raise ParseConflictError(
                (
                    "acquisition_run_id already exists with different document, "
                    "fingerprint, or settings"
                ),
                parse_run_id=request.acquisition_run_id,
                document_id=fingerprint.document_id,
            )

        source_copy_asset_path, source_copy_content_type = _source_copy_metadata(request)
        source_copy_path = run_store.put_binary(
            asset_path=source_copy_asset_path,
            content_type=source_copy_content_type,
            data=Path(request.source_path).read_bytes(),
        )
        source_fingerprint_path = run_store.put_json(
            artifact_kind="fingerprint",
            artifact_path="source/fingerprint.json",
            payload=fingerprint,
        )

        try:
            provider = self._provider or _default_provider(
                request,
                source_fingerprint=fingerprint,
            )
            ledger = provider.acquire(request)
            if request.source_kind is SourceDocumentKind.PDF:
                ledger = materialize_visual_assets(
                    source_path=request.source_path,
                    ledger=ledger,
                    store=run_store,
                    settings=request.settings,
                )
            (
                selected_source,
                outline_reports,
                selected_outline_entries,
                pymupdf_entries,
                pymupdf_rich_outline,
                pypdf_entries,
            ) = self._extract_outline_bundle(request)
        except ParseSubstrateError:
            raise
        except Exception as exc:  # pragma: no cover - safety net
            raise ExtractionFailureError(
                f"acquisition runtime failed: {exc}",
                document_id=fingerprint.document_id,
            ) from exc

        pymupdf_outline_path = run_store.put_json(
            artifact_kind="outline",
            artifact_path="outline/pymupdf.normalized.json",
            payload=pymupdf_entries,
        )
        pymupdf_rich_outline_path = run_store.put_json(
            artifact_kind="outline",
            artifact_path="outline/pymupdf.rich.json",
            payload=pymupdf_rich_outline,
        )
        pypdf_outline_path = run_store.put_json(
            artifact_kind="outline",
            artifact_path="outline/pypdf.normalized.json",
            payload=pypdf_entries,
        )
        selected_outline_path = run_store.put_json(
            artifact_kind="outline",
            artifact_path="outline/selected.json",
            payload={
                "selected_source": selected_source,
                "entries": selected_outline_entries,
            },
        )

        page_events = [event for page in ledger.pages for event in page.events]
        event_stream_path = run_store.put_jsonl(
            artifact_kind="events",
            artifact_path="events/document-events.jsonl",
            payloads=(*ledger.document_events, *page_events),
        )
        ledger_path = run_store.artifact_ref("ledger/canonical-document-ledger.json")

        embedded_manifest = ledger.acquisition_manifest.model_copy(
            update={
                "source_fingerprint_sha256": fingerprint.sha256,
                "settings_digest": digest,
                "acquisition_provider_identity": request.provider_identity,
                "selected_outline_source": selected_source,
                "outline_quality_reports": tuple(outline_reports),
                "selected_outline_entries": tuple(selected_outline_entries),
                "ledger_artifact_path": ledger_path,
                "outline_artifact_paths": (
                    pymupdf_outline_path,
                    pymupdf_rich_outline_path,
                    pypdf_outline_path,
                    selected_outline_path,
                    source_fingerprint_path,
                ),
                "event_stream_path": event_stream_path,
            }
        )
        persisted_ledger = ledger.model_copy(update={"acquisition_manifest": embedded_manifest})
        ledger_path = run_store.put_json(
            artifact_kind="ledger",
            artifact_path="ledger/canonical-document-ledger.json",
            payload=persisted_ledger,
        )
        total_unresolved_regions = 0
        for page in persisted_ledger.pages:
            log_event(
                self._logger,
                "PageNativeParsed",
                document_id=fingerprint.document_id,
                page_index=page.page_index,
                block_count=len(page.blocks),
            )
            unresolved = [block for block in page.blocks if isinstance(block, UnresolvedRegion)]
            total_unresolved_regions += len(unresolved)
            log_event(
                self._logger,
                "PageProfiled",
                document_id=fingerprint.document_id,
                page_index=page.page_index,
                unresolved_region_count=len(unresolved),
            )
            for unresolved_region in unresolved:
                log_event(
                    self._logger,
                    "UnresolvedRegionEmitted",
                    document_id=fingerprint.document_id,
                    page_index=page.page_index,
                    region_id=unresolved_region.region_id,
                    reason_code=unresolved_region.reason_code,
                )
        canonical_text_substrate = build_canonical_text_substrate(persisted_ledger)
        canonical_text_substrate_path = run_store.put_json(
            artifact_kind="projection",
            artifact_path="projection/canonical-text-substrate.json",
            payload=canonical_text_substrate,
        )
        projection = project_ledger_to_tree_synthesis_view(persisted_ledger)
        projection_view_path = run_store.put_json(
            artifact_kind="projection",
            artifact_path="projection/tree-synthesis-view.json",
            payload=projection,
        )
        log_event(
            self._logger,
            "ProjectionCreated",
            document_id=fingerprint.document_id,
            page_count=fingerprint.page_count,
            projection_path=projection_view_path,
        )

        manifest = AcquisitionRunManifest(
            acquisition_run_id=request.acquisition_run_id,
            document_id=fingerprint.document_id,
            artifact_root=artifact_root,
            source_fingerprint=fingerprint,
            settings=request.settings,
            settings_digest=digest,
            provider_identity=request.provider_identity,
            ledger_path=ledger_path,
            source_copy_path=source_copy_path,
            event_stream_path=event_stream_path,
            selected_outline_source=selected_source,
            outline_quality_reports=outline_reports,
            selected_outline_path=selected_outline_path,
            pymupdf_outline_path=pymupdf_outline_path,
            pymupdf_rich_outline_path=pymupdf_rich_outline_path,
            pypdf_outline_path=pypdf_outline_path,
            page_count=fingerprint.page_count,
            projection_view_path=projection_view_path,
            canonical_text_substrate_path=canonical_text_substrate_path,
        )
        manifest_path = run_store.put_json(
            artifact_kind="manifest",
            artifact_path="manifest.json",
            payload=manifest,
        )
        run_store.complete(
            manifest_ref=manifest_path,
            manifest=manifest,
        )
        log_event(
            self._logger,
            "AcquisitionCompleted",
            document_id=fingerprint.document_id,
            acquisition_run_id=request.acquisition_run_id,
            page_count=manifest.page_count,
            unresolved_region_count=total_unresolved_regions,
            manifest_ref=manifest_path,
        )
        return manifest

    def _extract_outline_bundle(
        self,
        request: AcquisitionRequest,
    ) -> tuple[
        OutlineSource,
        tuple[OutlineQualityReport, ...],
        tuple[OutlineEntry, ...],
        list[OutlineEntry],
        list[Any],
        list[OutlineEntry],
    ]:
        if request.source_kind is SourceDocumentKind.MARKDOWN:
            parsed = parse_markdown_source(
                request.source_path,
                settings=request.settings.markdown,
            )
            outline_entries = list(parsed.outline_entries)
            markdown_report = score_outline(outline_entries, OutlineSource.MARKDOWN)
            return (
                OutlineSource.MARKDOWN,
                (markdown_report,),
                tuple(outline_entries),
                [],
                [],
                [],
            )
        with open_document(request.source_path) as document:
            reader = PdfReader(request.source_path)
            pymupdf_rich, pymupdf_entries = extract_pymupdf_outlines(document)
            _, pypdf_entries = extract_pypdf_outlines(reader)
            selected_source, selected_entries, outline_reports = select_outline(
                pymupdf_entries,
                pypdf_entries,
            )
        return (
            selected_source,
            tuple(outline_reports),
            tuple(selected_entries),
            pymupdf_entries,
            pymupdf_rich,
            pypdf_entries,
        )


def acquire_document(
    request: AcquisitionRequest,
    *,
    logger: Logger | None = None,
    storage: StorageConfig | None = None,
) -> AcquisitionRunManifest:
    """Acquire a document through the deterministic v2 runtime."""

    return AcquisitionService(logger=logger, storage=storage).acquire(request)


def acquire_batch(
    requests: Sequence[AcquisitionRequest],
    *,
    storage: StorageConfig | None = None,
    provider: AcquisitionProvider | None = None,
    max_workers: int = 4,
    logger: Logger | None = None,
) -> BatchResult[AcquisitionRunManifest]:
    """Acquire multiple documents concurrently with per-item failure isolation.

    Each request is processed by an independent ``AcquisitionService`` in a
    ``ThreadPoolExecutor`` worker thread.  A failure in one document does not
    abort the batch; failed items are collected in ``BatchResult.failed``.

    Args:
        requests: Sequence of acquisition requests to process.
        storage: Storage backend config shared by all workers.
        provider: Optional custom ``AcquisitionProvider`` passed to every worker.
        max_workers: Thread-pool size.  Defaults to 4.
        logger: Optional logger propagated to every worker service instance.

    Returns:
        A ``BatchResult[AcquisitionRunManifest]`` with per-document outcomes.
    """
    successful: list[AcquisitionRunManifest] = []
    failed: list[BatchItemFailure] = []

    futures: list[Future[AcquisitionRunManifest]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for req in requests:
            service = AcquisitionService(provider=provider, logger=logger, storage=storage)
            futures.append(executor.submit(service.acquire, req))

    for idx, future in enumerate(futures):
        exc = future.exception()
        if exc is None:
            successful.append(future.result())
        else:
            failed.append(
                BatchItemFailure(
                    item_index=idx,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )

    return BatchResult(successful=tuple(successful), failed=tuple(failed))


async def async_acquire_batch(
    requests: Sequence[AcquisitionRequest],
    *,
    storage: StorageConfig | None = None,
    provider: AcquisitionProvider | None = None,
    max_workers: int = 4,
    logger: Logger | None = None,
) -> BatchResult[AcquisitionRunManifest]:
    """Acquire multiple documents concurrently using asyncio fan-out."""
    if max_workers < 1:
        msg = "max_workers must be greater than or equal to 1"
        raise ValueError(msg)

    request_list = tuple(requests)
    if not request_list:
        return BatchResult(successful=(), failed=())

    semaphore = asyncio.Semaphore(min(max_workers, len(request_list)))
    results: list[AcquisitionRunManifest | Exception | None] = [None] * len(request_list)
    service = AcquisitionService(provider=provider, logger=logger, storage=storage)

    async def _acquire_one(index: int, request: AcquisitionRequest) -> None:
        async with semaphore:
            try:
                results[index] = await asyncio.to_thread(service.acquire, request)
            except Exception as exc:
                results[index] = exc

    await asyncio.gather(
        *(_acquire_one(index, request) for index, request in enumerate(request_list))
    )

    successful: list[AcquisitionRunManifest] = []
    failed: list[BatchItemFailure] = []
    for idx, result in enumerate(results):
        if isinstance(result, Exception):
            failed.append(
                BatchItemFailure(
                    item_index=idx,
                    error_type=type(result).__name__,
                    error_message=str(result),
                )
            )
            continue
        if result is None:
            failed.append(
                BatchItemFailure(
                    item_index=idx,
                    error_type="InternalError",
                    error_message="acquisition completed without result",
                )
            )
            continue
        successful.append(result)

    return BatchResult(successful=tuple(successful), failed=tuple(failed))
