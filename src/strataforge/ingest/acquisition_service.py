"""Parallel v2 acquisition + projection orchestration."""

from __future__ import annotations

from typing import Any

import fitz
from pypdf import PdfReader
from pypdf import __version__ as pypdf_version

from strataforge.constants import CERTIFIED_PYMUPDF_VERSIONS, CERTIFIED_PYPDF_VERSIONS
from strataforge.domain.models import (
    AcquisitionRequest,
    AcquisitionRunIndex,
    AcquisitionRunManifest,
    AcquisitionSettings,
    OutlineEntry,
    OutlineQualityReport,
    OutlineSource,
    UnresolvedRegion,
)
from strataforge.ingest.acquisition_artifacts import (
    AcquisitionArtifactStore,
    settings_digest,
)
from strataforge.ingest.errors import (
    ExtractionFailureError,
    ParseConflictError,
    ParseSubstrateError,
)
from strataforge.ingest.fingerprint import fingerprint_document
from strataforge.ingest.outline import (
    extract_pymupdf_outlines,
    extract_pypdf_outlines,
    select_outline,
)
from strataforge.ingest.projection import (
    build_canonical_text_substrate,
    project_ledger_to_tree_synthesis_view,
)
from strataforge.ingest.protocols import AcquisitionProvider
from strataforge.ingest.providers.native_pymupdf import NativePyMuPDFAcquisitionProvider
from strataforge.ingest.visual_assets import materialize_visual_assets
from strataforge.observability import (
    AcquisitionStarted,
    EventBus,
    PageNativeParsed,
    PageProfiled,
    ProjectionCreated,
    SourceFingerprintComputed,
    UnresolvedRegionEmitted,
)

fitz_module: Any = fitz


def _default_provider(request: AcquisitionRequest) -> AcquisitionProvider:
    if request.provider_identity == "native_pymupdf":
        return NativePyMuPDFAcquisitionProvider()
    msg = f"unsupported acquisition provider identity: {request.provider_identity}"
    raise ExtractionFailureError(msg, document_id="unknown")


class AcquisitionService:
    """Filesystem-backed deterministic acquisition + projection runtime."""

    def __init__(
        self,
        provider: AcquisitionProvider | None = None,
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self._provider = provider
        self._event_bus = event_bus

    def acquire(self, request: AcquisitionRequest) -> AcquisitionRunManifest:
        self._validate_provider_versions(request.settings)
        fingerprint = fingerprint_document(request.source_path)
        if self._event_bus is not None:
            self._event_bus.publish(
                SourceFingerprintComputed(
                    event_id=f"{fingerprint.document_id}-fingerprint",
                    event_name="SourceFingerprintComputed",
                    document_id=fingerprint.document_id,
                    source_path=fingerprint.source_path,
                    sha256=fingerprint.sha256,
                )
            )
            self._event_bus.publish(
                AcquisitionStarted(
                    event_id=f"{request.acquisition_run_id}-started",
                    event_name="AcquisitionStarted",
                    document_id=fingerprint.document_id,
                    acquisition_run_id=request.acquisition_run_id,
                    provider_identity=request.provider_identity,
                )
            )
        store = AcquisitionArtifactStore(
            request.artifact_root,
            request.acquisition_run_id,
            fingerprint.document_id,
        )
        digest = settings_digest(request.settings)
        run_index = store.load_run_index()
        if run_index is not None:
            if (
                run_index.document_id == fingerprint.document_id
                and run_index.source_fingerprint_sha256 == fingerprint.sha256
                and run_index.settings_digest == digest
            ):
                manifest = store.load_manifest_at(run_index.manifest_path)
                if manifest is None:
                    msg = "acquisition_run_id index points to a missing manifest"
                    raise ExtractionFailureError(msg, document_id=fingerprint.document_id)
                return manifest
            raise ParseConflictError(
                (
                    "acquisition_run_id already exists with different document, "
                    "fingerprint, or settings"
                ),
                parse_run_id=request.acquisition_run_id,
                document_id=fingerprint.document_id,
            )

        store.ensure()
        source_copy_path = store.copy_source(request.source_path)
        source_fingerprint_path = store.write_json("source/fingerprint.json", fingerprint)

        try:
            provider = self._provider or _default_provider(request)
            ledger = provider.acquire(request)
            ledger = materialize_visual_assets(
                source_path=request.source_path,
                ledger=ledger,
                store=store,
                settings=request.settings,
            )
            (
                selected_source,
                outline_reports,
                selected_outline_entries,
                pymupdf_entries,
                pymupdf_rich_outline,
                pypdf_entries,
            ) = self._extract_outline_bundle(request.source_path)
        except ParseSubstrateError:
            raise
        except Exception as exc:  # pragma: no cover - safety net
            raise ExtractionFailureError(
                f"acquisition runtime failed: {exc}",
                document_id=fingerprint.document_id,
            ) from exc

        pymupdf_outline_path = store.write_json("outline/pymupdf.normalized.json", pymupdf_entries)
        pymupdf_rich_outline_path = store.write_json(
            "outline/pymupdf.rich.json", pymupdf_rich_outline
        )
        pypdf_outline_path = store.write_json("outline/pypdf.normalized.json", pypdf_entries)
        selected_outline_path = store.write_json(
            "outline/selected.json",
            {
                "selected_source": selected_source,
                "entries": selected_outline_entries,
            },
        )

        page_events = [event for page in ledger.pages for event in page.events]
        event_stream_path = store.write_jsonl(
            "events/document-events.jsonl",
            (*ledger.document_events, *page_events),
        )

        embedded_manifest = ledger.acquisition_manifest.model_copy(
            update={
                "source_fingerprint_sha256": fingerprint.sha256,
                "settings_digest": digest,
                "acquisition_provider_identity": request.provider_identity,
                "selected_outline_source": selected_source,
                "outline_quality_reports": tuple(outline_reports),
                "selected_outline_entries": tuple(selected_outline_entries),
                "ledger_artifact_path": str(
                    store.absolute("ledger", "canonical-document-ledger.json")
                ),
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
        ledger_path = store.write_json("ledger/canonical-document-ledger.json", persisted_ledger)
        if self._event_bus is not None:
            for page in persisted_ledger.pages:
                self._event_bus.publish(
                    PageNativeParsed(
                        event_id=f"{fingerprint.document_id}-native-{page.page_index}",
                        event_name="PageNativeParsed",
                        document_id=fingerprint.document_id,
                        page_index=page.page_index,
                        block_count=len(page.blocks),
                    )
                )
                unresolved = [block for block in page.blocks if isinstance(block, UnresolvedRegion)]
                self._event_bus.publish(
                    PageProfiled(
                        event_id=f"{fingerprint.document_id}-profiled-{page.page_index}",
                        event_name="PageProfiled",
                        document_id=fingerprint.document_id,
                        page_index=page.page_index,
                        unresolved_region_count=len(unresolved),
                    )
                )
                for unresolved_region in unresolved:
                    self._event_bus.publish(
                        UnresolvedRegionEmitted(
                            event_id=unresolved_region.region_id,
                            event_name="UnresolvedRegionEmitted",
                            document_id=fingerprint.document_id,
                            page_index=page.page_index,
                            region_id=unresolved_region.region_id,
                            reason_code=unresolved_region.reason_code,
                        )
                    )
        canonical_text_substrate = build_canonical_text_substrate(persisted_ledger)
        canonical_text_substrate_path = store.write_json(
            "projection/canonical-text-substrate.json",
            canonical_text_substrate,
        )
        projection = project_ledger_to_tree_synthesis_view(persisted_ledger)
        projection_view_path = store.write_json("projection/tree-synthesis-view.json", projection)
        if self._event_bus is not None:
            self._event_bus.publish(
                ProjectionCreated(
                    event_id=f"{fingerprint.document_id}-projection",
                    event_name="ProjectionCreated",
                    document_id=fingerprint.document_id,
                    page_count=fingerprint.page_count,
                    projection_path=projection_view_path,
                )
            )

        manifest = AcquisitionRunManifest(
            acquisition_run_id=request.acquisition_run_id,
            document_id=fingerprint.document_id,
            artifact_root=str(store.base_path),
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
        manifest_path = store.write_manifest(manifest)
        store.write_run_index(
            AcquisitionRunIndex(
                acquisition_run_id=request.acquisition_run_id,
                document_id=fingerprint.document_id,
                source_fingerprint_sha256=fingerprint.sha256,
                settings_digest=digest,
                manifest_path=manifest_path,
            )
        )
        return manifest

    def _extract_outline_bundle(
        self,
        source_path: str,
    ) -> tuple[
        OutlineSource,
        tuple[OutlineQualityReport, ...],
        tuple[OutlineEntry, ...],
        list[OutlineEntry],
        list[Any],
        list[OutlineEntry],
    ]:
        with fitz_module.open(source_path) as document:
            reader = PdfReader(source_path)
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

    def _validate_provider_versions(self, settings: AcquisitionSettings) -> None:
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
            raise ExtractionFailureError(msg, document_id="unknown")
        if pypdf_version != settings.pypdf_version:
            msg = (
                f"configured pypdf version {settings.pypdf_version} "
                f"does not match installed {pypdf_version}"
            )
            raise ExtractionFailureError(msg, document_id="unknown")


def acquire_document(
    request: AcquisitionRequest,
    *,
    event_bus: EventBus | None = None,
) -> AcquisitionRunManifest:
    """Acquire a document through the deterministic v2 runtime."""

    return AcquisitionService(event_bus=event_bus).acquire(request)
