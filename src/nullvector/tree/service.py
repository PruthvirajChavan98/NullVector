"""LLM-driven tree pipeline orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Any, cast

from nullvector.domain.common import BatchItemFailure, BatchResult, ScalarValue
from nullvector.domain.ledger import (
    AcquisitionRunManifest,
    OutlineEntry,
    OutlineSource,
)
from nullvector.domain.tree import (
    DecompositionMethod,
    DecompositionReport,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeRunIndex,
)
from nullvector.llm.errors import GatewayAuthError, GatewayConfigurationError
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage._serialization import (
    canonical_json_text,
    run_identity_matches,
    settings_digest,
)
from nullvector.tree.llm_hierarchy import LLMHierarchyBuilder
from nullvector.tree.page_data import PageData

_BATCH_FATAL_ERRORS = (GatewayAuthError, GatewayConfigurationError)


class TreePipelineError(Exception):
    """Base class for tree build failures."""


class TreeConflictError(TreePipelineError):
    """Raised when a tree run id is reused with different effective inputs."""


@dataclass(frozen=True)
class TreeInputBundle:
    """Resolved inputs for one tree build."""

    manifest_path: str
    artifact_root: Path | None
    registry_root: Path
    document_id: str
    page_count: int
    input_identity: str
    fingerprint_sha256: str
    outline_entries: tuple[OutlineEntry, ...]
    markdown_pages: tuple[str, ...]


class TreePipelineService:
    """Storage-backed LLM-driven tree pipeline orchestrator."""

    def __init__(
        self,
        *,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._logger = resolve_runtime_logger(logger)
        self._storage = storage

    def build(
        self,
        request: TreeBuildRequest,
        *,
        gateway: StructuredLLMGateway | None = None,
    ) -> TreeBuildManifest:
        """Build a hierarchy tree from persisted acquisition artifacts."""

        input_bundle = self._resolve_input_bundle(request)
        digest = settings_digest(request.settings)
        effective_tree_root = self._effective_tree_root(input_bundle, request)

        store = build_document_store(
            self._storage,
            default_filesystem_root=str(effective_tree_root),
        )
        artifact_root = store.resolve_artifact_root(
            run_type="tree",
            run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
            configured_root=str(effective_tree_root),
        )

        run_index = TreeRunIndex(
            tree_run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
            registry_root=str(input_bundle.registry_root),
            acquisition_manifest_path=input_bundle.manifest_path,
            acquisition_artifact_identity=input_bundle.input_identity,
            acquisition_fingerprint_sha256=input_bundle.fingerprint_sha256,
            settings_digest=digest,
        )
        expected_identity: dict[str, ScalarValue] = {
            "document_id": input_bundle.document_id,
            "acquisition_artifact_identity": input_bundle.input_identity,
            "settings_digest": digest,
        }
        created, run_record = store.reserve_run(
            run_type="tree",
            run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
            artifact_root=artifact_root,
            identity=expected_identity,
        )
        run_store = store.for_run(
            run_type="tree",
            run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
        )

        if not created:
            existing = self._try_reuse(run_record, expected_identity, store)
            if existing is not None:
                return existing
            raise TreeConflictError(
                "tree_run_id already exists with different acquisition input or settings"
            )

        # Run index
        run_index_path = run_store.put_json(
            artifact_kind="run_index",
            artifact_path="registry/run-index.json",
            payload=run_index,
        )

        # Hierarchy synthesis
        builder = LLMHierarchyBuilder(gateway=gateway)
        committed_nodes, node_cards, unassigned_spans, build_report = builder.build(
            document_id=input_bundle.document_id,
            tree_run_id=request.tree_run_id,
            markdown_pages=input_bundle.markdown_pages,
            outline_entries=input_bundle.outline_entries,
        )

        # Persist hierarchy artifacts
        committed_hierarchy_path = run_store.put_json(
            artifact_kind="hierarchy",
            artifact_path="hierarchy/committed.json",
            payload=committed_nodes,
        )
        node_cards_path = run_store.put_json(
            artifact_kind="node_cards",
            artifact_path="hierarchy/node-cards.json",
            payload=node_cards,
        )
        unassigned_spans_path = run_store.put_json(
            artifact_kind="artifact",
            artifact_path="unassigned-spans.json",
            payload=unassigned_spans,
        )
        build_report_path = run_store.put_json(
            artifact_kind="report",
            artifact_path="build-report.json",
            payload=build_report,
        )

        # Optional summarization
        node_summaries_path: str | None = None
        if request.summarize:
            if gateway is None:
                raise TreePipelineError("summarize=True requires a configured gateway")
            from nullvector.semantic.summarize import NodeSummarizer

            page_data = tuple(
                PageData(page_index=i, text=text)
                for i, text in enumerate(input_bundle.markdown_pages)
            )
            summarizer = NodeSummarizer(gateway=gateway, logger=self._logger)
            committed_nodes_tuple, node_cards, node_summaries = summarizer.summarize(
                nodes=committed_nodes,
                pages=page_data,
            )
            committed_nodes = committed_nodes_tuple
            node_summaries_path = run_store.put_json(
                artifact_kind="summary",
                artifact_path="summaries/node-summaries.json",
                payload=node_summaries,
            )

        decomposition_report = DecompositionReport(
            decomposition_method=DecompositionMethod.NONE,
        )
        decomposition_report_path = run_store.put_json(
            artifact_kind="report",
            artifact_path="decomposition/report.json",
            payload=decomposition_report,
        )

        # Emit events
        for node in committed_nodes:
            log_event(
                self._logger,
                "NodeCommitted",
                document_id=input_bundle.document_id,
                tree_run_id=request.tree_run_id,
                node_id=node.node_id,
                title=node.title,
            )
        log_event(
            self._logger,
            "HierarchySynthesisCompleted",
            document_id=input_bundle.document_id,
            tree_run_id=request.tree_run_id,
            synthesis_method=build_report.synthesis_method,
        )

        # Build and persist manifest
        manifest = TreeBuildManifest(
            tree_run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
            registry_root=str(input_bundle.registry_root),
            acquisition_manifest_path=input_bundle.manifest_path,
            acquisition_artifact_identity=input_bundle.input_identity,
            acquisition_fingerprint_sha256=input_bundle.fingerprint_sha256,
            artifact_root=artifact_root,
            settings=request.settings,
            settings_digest=digest,
            run_index_path=run_index_path,
            committed_hierarchy_path=committed_hierarchy_path,
            node_cards_path=node_cards_path,
            unassigned_spans_path=unassigned_spans_path,
            build_report_path=build_report_path,
            node_summaries_path=node_summaries_path,
            decomposition_report_path=decomposition_report_path,
            committed_node_count=len(committed_nodes),
            unassigned_span_count=len(unassigned_spans),
        )
        manifest_path = run_store.put_json(
            artifact_kind="manifest",
            artifact_path="manifest.json",
            payload=manifest,
        )
        run_store.complete(manifest_ref=manifest_path, manifest=manifest)

        log_event(
            self._logger,
            "TreeBuildCompleted",
            document_id=input_bundle.document_id,
            tree_run_id=request.tree_run_id,
            committed_node_count=len(committed_nodes),
            unassigned_span_count=len(unassigned_spans),
            manifest_ref=manifest_path,
        )
        return manifest

    def _resolve_input_bundle(self, request: TreeBuildRequest) -> TreeInputBundle:
        """Load acquisition manifest and extract VLM Markdown pages."""

        manifest_path = request.acquisition_manifest_path
        from nullvector._client_utils import load_model_artifact

        acq_manifest = load_model_artifact(
            AcquisitionRunManifest,
            manifest_path,
            storage=self._storage,
        )

        # Load ledger to extract page text
        import json as _json

        ledger_path = acq_manifest.ledger_path
        if self._storage is None:
            ledger_data = cast(
                dict[str, Any],
                _json.loads(Path(ledger_path).read_text(encoding="utf-8")),
            )
        else:
            store = build_document_store(
                self._storage,
                default_filesystem_root=str(
                    Path(acq_manifest.artifact_root).parent
                    if acq_manifest.artifact_root
                    else "artifacts"
                ),
            )
            ledger_data = cast(dict[str, Any], store.read_json_artifact(ledger_path))
        pages_data = cast(list[dict[str, Any]], ledger_data.get("pages", []))

        markdown_pages: list[str] = []
        for page in pages_data:
            blocks = cast(list[dict[str, Any]], page.get("blocks", []))
            page_text = "\n".join(
                block["content"] for block in blocks if block.get("block_type") == "text_block"
            )
            markdown_pages.append(page_text)

        artifact_root = (
            Path(acq_manifest.artifact_root) if acq_manifest.artifact_root is not None else None
        )
        registry_root = (
            artifact_root.parent if artifact_root is not None else Path("artifacts/tree_runs")
        )

        return TreeInputBundle(
            manifest_path=manifest_path,
            artifact_root=artifact_root,
            registry_root=registry_root,
            document_id=acq_manifest.document_id,
            page_count=acq_manifest.page_count,
            input_identity=str(Path(manifest_path).resolve()),
            fingerprint_sha256=acq_manifest.source_fingerprint.sha256,
            outline_entries=self._load_outline_entries(acq_manifest),
            markdown_pages=tuple(markdown_pages),
        )

    def _effective_tree_root(
        self, input_bundle: TreeInputBundle, request: TreeBuildRequest
    ) -> Path:
        if input_bundle.artifact_root is not None:
            base = input_bundle.artifact_root.parent
        else:
            base = Path("artifacts/tree_runs")
        return base / request.tree_run_id / input_bundle.document_id

    def _load_outline_entries(
        self, acq_manifest: AcquisitionRunManifest
    ) -> tuple[OutlineEntry, ...]:
        """Load outline entries from the persisted selected outline artifact."""

        import json as _json

        outline_path = acq_manifest.selected_outline_path
        if self._storage is None:
            path = Path(outline_path)
            if not path.exists():
                return ()
            payload = cast(dict[str, Any], _json.loads(path.read_text(encoding="utf-8")))
        else:
            store = build_document_store(
                self._storage,
                default_filesystem_root=str(
                    Path(acq_manifest.artifact_root).parent
                    if acq_manifest.artifact_root
                    else "artifacts"
                ),
            )
            payload = cast(dict[str, Any], store.read_json_artifact(outline_path))

        entries_raw = cast(list[dict[str, Any]], payload.get("entries", []))
        return tuple(
            OutlineEntry.model_validate(
                {**entry, "source": OutlineSource(entry["source"])} if "source" in entry else entry
            )
            for entry in entries_raw
        )

    def _try_reuse(
        self,
        run_record: dict[str, Any],
        expected_identity: dict[str, ScalarValue],
        store: Any,
    ) -> TreeBuildManifest | None:
        if not run_identity_matches(run_record, expected_identity):
            return None
        manifest_ref = cast(
            str | None,
            run_record.get("manifest_ref") or run_record.get("manifest_path"),
        )
        if manifest_ref is None:
            return None
        return TreeBuildManifest.model_validate_json(
            canonical_json_text(store.read_json_artifact(manifest_ref))
        )


def build_tree(
    request: TreeBuildRequest,
    *,
    gateway: StructuredLLMGateway | None = None,
    logger: Logger | None = None,
    storage: StorageConfig | None = None,
) -> TreeBuildManifest:
    """Build a tree from persisted acquisition artifacts."""

    return TreePipelineService(logger=logger, storage=storage).build(
        request,
        gateway=gateway,
    )


def build_tree_batch(
    requests: Sequence[TreeBuildRequest],
    *,
    storage: StorageConfig | None = None,
    gateway: StructuredLLMGateway | None = None,
    max_workers: int = 4,
    logger: Logger | None = None,
) -> BatchResult[TreeBuildManifest]:
    """Build hierarchy trees for multiple documents concurrently."""

    successful: list[TreeBuildManifest] = []
    failed: list[BatchItemFailure] = []
    first_batch_fatal: Exception | None = None

    def _build_one(request: TreeBuildRequest) -> TreeBuildManifest:
        service = TreePipelineService(logger=logger, storage=storage)
        return service.build(request, gateway=gateway)

    futures: list[Future[TreeBuildManifest]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for req in requests:
            futures.append(executor.submit(_build_one, req))

    for idx, future in enumerate(futures):
        exc = future.exception()
        if exc is None:
            successful.append(future.result())
        else:
            if first_batch_fatal is None and isinstance(exc, _BATCH_FATAL_ERRORS):
                first_batch_fatal = exc
                continue
            failed.append(
                BatchItemFailure(
                    item_index=idx,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )

    if first_batch_fatal is not None:
        raise first_batch_fatal

    return BatchResult(successful=tuple(successful), failed=tuple(failed))


async def async_build_tree_batch(
    requests: Sequence[TreeBuildRequest],
    *,
    storage: StorageConfig | None = None,
    gateway: StructuredLLMGateway | None = None,
    max_workers: int = 4,
    logger: Logger | None = None,
) -> BatchResult[TreeBuildManifest]:
    """Build hierarchy trees concurrently using asyncio fan-out."""

    if max_workers < 1:
        msg = "max_workers must be greater than or equal to 1"
        raise ValueError(msg)

    request_list = tuple(requests)
    if not request_list:
        return BatchResult(successful=(), failed=())

    semaphore = asyncio.Semaphore(min(max_workers, len(request_list)))
    results: list[TreeBuildManifest | Exception | None] = [None] * len(request_list)

    async def _build_one(index: int, request: TreeBuildRequest) -> None:
        async with semaphore:
            service = TreePipelineService(logger=logger, storage=storage)
            try:
                results[index] = await asyncio.to_thread(
                    service.build,
                    request,
                    gateway=gateway,
                )
            except Exception as exc:
                results[index] = exc

    await asyncio.gather(
        *(_build_one(index, request) for index, request in enumerate(request_list))
    )

    successful: list[TreeBuildManifest] = []
    failed: list[BatchItemFailure] = []
    first_batch_fatal: Exception | None = None
    for idx, result in enumerate(results):
        if isinstance(result, Exception):
            if first_batch_fatal is None and isinstance(result, _BATCH_FATAL_ERRORS):
                first_batch_fatal = result
                continue
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
                    error_message="tree build completed without result",
                )
            )
            continue
        successful.append(result)

    if first_batch_fatal is not None:
        raise first_batch_fatal

    return BatchResult(successful=tuple(successful), failed=tuple(failed))
