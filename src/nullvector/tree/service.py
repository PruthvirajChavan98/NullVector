"""Artifact-driven Phase 02 tree pipeline orchestration."""

from __future__ import annotations

import gzip
import json
import shutil
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Any, cast

from nullvector.domain.common import BatchItemFailure, BatchResult
from nullvector.domain.ledger import (
    AcquisitionRunManifest,
    CanonicalTextSubstrate,
    OutlineEntry,
    OutlineQualityReport,
    OutlineSource,
)
from nullvector.domain.tree import (
    DecompositionMethod,
    HeadingCandidate,
    HierarchyBuildReport,
    HierarchyNode,
    HierarchyStrategy,
    OutlineAnchorRecord,
    OutlineTrustMode,
    RepairDecision,
    RepairStatus,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeRunIndex,
    VerificationStatus,
)
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.observability.logging import log_event
from nullvector.runtime_validation import validate_canonical_text_substrate_contract
from nullvector.storage import StorageBackend, StorageConfig, build_document_store
from nullvector.storage._serialization import (
    canonical_json_text,
    run_identity_matches,
    settings_digest,
    write_json_file,
)
from nullvector.storage.protocol import DocumentStore, RunScopedStore
from nullvector.tree.anchors import attach_content_anchors
from nullvector.tree.decompose import NodeDecomposer
from nullvector.tree.headings import (
    PageArtifacts,
    extract_inferred_candidates,
    extract_outline_candidates_with_records,
)
from nullvector.tree.hierarchy import (
    attach_default_owned_spans,
    build_hierarchy,
    compute_unassigned_spans,
    determine_outline_trust_mode,
    project_node_cards,
    reconcile_heading_candidates,
)
from nullvector.tree.repair import NoopRepairEngine, RepairEngine
from nullvector.tree.strategy import (
    StrategyAttemptResult,
    execute_hierarchy_strategy,
)
from nullvector.tree.summarize import NodeSummarizer
from nullvector.tree.toc import TocDetector
from nullvector.tree.toc_reconcile import TocReconciler
from nullvector.tree.verify import LLMVerificationAssistant, verify_hierarchy


class TreePipelineError(Exception):
    """Base class for deterministic Phase 02 tree build failures."""


class TreeConflictError(TreePipelineError):
    """Raised when a tree run id is reused with different effective inputs."""


@dataclass(frozen=True)
class TreeInputBundle:
    """Normalized tree input boundary over acquisition manifests."""

    manifest_path: str
    artifact_root: Path | None
    registry_root: Path
    document_id: str
    page_count: int
    input_identity: str
    fingerprint_sha256: str
    selected_source: OutlineSource
    outline_entries: tuple[OutlineEntry, ...]
    outline_anchor_records: tuple[OutlineAnchorRecord, ...]
    outline_quality_reports: tuple[OutlineQualityReport, ...]
    pages: tuple[PageArtifacts, ...]


def _read_json(path: Path) -> Any:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_acquisition_manifest(
    store: DocumentStore,
    acquisition_manifest_path: str,
) -> AcquisitionRunManifest:
    return AcquisitionRunManifest.model_validate_json(
        canonical_json_text(store.read_json_artifact(acquisition_manifest_path))
    )


def _resolve_tree_registry_root(
    input_root: Path,
    *,
    input_run_id: str,
    document_id: str,
) -> Path:
    if input_root.name == document_id and input_root.parent.name == input_run_id:
        return input_root.parent.parent / "_tree_runs"
    return input_root.parent / "_tree_runs"


def _load_acquisition_outline_entries(
    store: DocumentStore,
    acquisition_manifest: AcquisitionRunManifest,
) -> tuple[OutlineSource, tuple[OutlineEntry, ...]]:
    payload = cast(
        dict[str, Any], store.read_json_artifact(acquisition_manifest.selected_outline_path)
    )
    selected_source = OutlineSource(
        payload.get("selected_source", acquisition_manifest.selected_outline_source)
    )
    entries = tuple(
        OutlineEntry.model_validate({**entry, "source": OutlineSource(entry["source"])})
        for entry in cast(list[dict[str, Any]], payload.get("entries", []))
    )
    return selected_source, entries


def _load_canonical_text_substrate(
    store: DocumentStore,
    acquisition_manifest: AcquisitionRunManifest,
) -> CanonicalTextSubstrate:
    try:
        substrate_ref = validate_canonical_text_substrate_contract(manifest=acquisition_manifest)
    except ValueError as exc:
        raise TreePipelineError(str(exc)) from exc
    return CanonicalTextSubstrate.model_validate_json(
        canonical_json_text(store.read_json_artifact(substrate_ref))
    )


def _load_projection_page_artifacts(
    text_substrate: CanonicalTextSubstrate,
) -> tuple[PageArtifacts, ...]:
    pages: list[PageArtifacts] = []
    for page in sorted(text_substrate.pages, key=lambda item: item.page_index):
        pages.append(
            PageArtifacts(
                page_index=page.page_index,
                text=page.text,
                rawdict=None,
                page_label=page.page_label,
                canonical_lines=page.lines,
            )
        )
    return tuple(pages)


def _load_tree_input_bundle(
    request: TreeBuildRequest,
    *,
    store: DocumentStore,
) -> TreeInputBundle:
    acquisition_manifest_path = (
        request.acquisition_manifest_path
        if request.acquisition_manifest_path.startswith("pg://")
        else str(Path(request.acquisition_manifest_path).resolve())
    )
    acquisition_manifest = _load_acquisition_manifest(store, acquisition_manifest_path)
    _raw_root = acquisition_manifest.artifact_root
    if _raw_root is not None:
        acquisition_root: Path | None = Path(_raw_root)
    else:
        acquisition_root = None
    selected_source, outline_entries = _load_acquisition_outline_entries(
        store, acquisition_manifest
    )
    text_substrate = _load_canonical_text_substrate(store, acquisition_manifest)
    pages = _load_projection_page_artifacts(text_substrate)
    _, outline_anchor_records = extract_outline_candidates_with_records(
        acquisition_manifest.document_id,
        pages,
        outline_entries,
        settings=request.settings,
    )
    _registry_root = (
        _resolve_tree_registry_root(
            acquisition_root,
            input_run_id=acquisition_manifest.acquisition_run_id,
            document_id=acquisition_manifest.document_id,
        )
        if acquisition_root is not None
        else Path("_tree_runs")
    )
    return TreeInputBundle(
        manifest_path=acquisition_manifest_path,
        artifact_root=acquisition_root,
        registry_root=_registry_root,
        document_id=acquisition_manifest.document_id,
        page_count=acquisition_manifest.page_count,
        input_identity=str(acquisition_manifest_path),
        fingerprint_sha256=acquisition_manifest.source_fingerprint.sha256,
        selected_source=selected_source,
        outline_entries=outline_entries,
        outline_anchor_records=outline_anchor_records,
        outline_quality_reports=tuple(acquisition_manifest.outline_quality_reports),
        pages=pages,
    )


def _load_hierarchy_nodes(path: str) -> tuple[HierarchyNode, ...]:
    return tuple(
        HierarchyNode.model_validate_json(json.dumps(item))
        for item in cast(list[dict[str, Any]], _read_json(Path(path)))
    )


def _detect_explicit_gap_pages(
    pages: tuple[PageArtifacts, ...],
    inferred_candidates: tuple[HeadingCandidate, ...],
) -> set[int]:
    kept_heading_pages = {
        candidate.page_index for candidate in inferred_candidates if candidate.keep
    }
    gap_pages: set[int] = set()
    for page in pages:
        if page.page_index in kept_heading_pages:
            continue
        first_line = next(
            (line.strip() for line in page.text.splitlines() if line.strip()),
            "",
        ).casefold()
        if first_line.startswith(("figure ", "table ", "appendix marker ")):
            gap_pages.add(page.page_index)
    return gap_pages


def _strategy_attempt_root(
    tree_root: Path,
    *,
    attempt_index: int,
    strategy: HierarchyStrategy,
) -> Path:
    return tree_root / "strategy" / "attempts" / f"{attempt_index:02d}-{strategy.value}"


def _unassigned_page_count(unassigned_spans: tuple[Any, ...]) -> int:
    """Return the number of pages represented by explicit unassigned spans."""

    return sum(span.page_span.end_page - span.page_span.start_page + 1 for span in unassigned_spans)


def _persist_tree_json(
    run_store: RunScopedStore,
    *,
    artifact_kind: str,
    artifact_path: str,
    payload: Any | None = None,
    source_path: str | None = None,
) -> str | None:
    if payload is None:
        if source_path is None:
            return None
        payload = _read_json(Path(source_path))
    return run_store.put_json(
        artifact_kind=artifact_kind,
        artifact_path=artifact_path,
        payload=payload,
    )


def _tree_manifest_artifact_root(
    *,
    backend: StorageBackend,
    tree_root: Path | None,
    run_id: str,
    document_id: str,
) -> str | None:
    if backend is StorageBackend.POSTGRES:
        return None
    return str(tree_root) if tree_root is not None else None


def _cleanup_attempt_artifacts(tree_root: Path) -> None:
    shutil.rmtree(tree_root / "strategy" / "attempts", ignore_errors=True)


def _persist_tree_run_index(
    store: DocumentStore,
    run_store: RunScopedStore,
    *,
    run_index_path: Path,
    run_index: TreeRunIndex,
) -> str:
    if store.backend is StorageBackend.POSTGRES:
        return run_store.put_json(
            artifact_kind="run_index",
            artifact_path="registry/run-index.json",
            payload=run_index,
        )
    return store.put_json_artifact(
        run_type=run_store.run_type,
        run_id=run_store.run_id,
        document_id=run_store.document_id,
        artifact_kind="run_index",
        artifact_path=str(run_index_path),
        payload=run_index,
    )


def _load_tree_manifest_from_ref(store: DocumentStore, manifest_ref: str) -> TreeBuildManifest:
    return TreeBuildManifest.model_validate_json(
        canonical_json_text(store.read_json_artifact(manifest_ref))
    )


def _load_tree_run_index(path: Path) -> TreeRunIndex:
    return TreeRunIndex.model_validate_json(path.read_text(encoding="utf-8"))


def _load_build_report(path: str) -> HierarchyBuildReport:
    return HierarchyBuildReport.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _load_node_summaries_payload(path: str | None) -> tuple[dict[str, Any], ...] | None:
    if path is None:
        return None
    payload = _read_json(Path(path))
    return tuple(cast(list[dict[str, Any]], payload))


def _build_strategy_attempt(
    *,
    request: TreeBuildRequest,
    tree_root: Path,
    attempt_index: int,
    strategy: HierarchyStrategy,
    document_id: str,
    page_count: int,
    selected_source: OutlineSource,
    outline_reports: tuple[Any, ...],
    pages: tuple[PageArtifacts, ...],
    outline_candidates: tuple[HeadingCandidate, ...],
    outline_anchor_records: tuple[OutlineAnchorRecord, ...],
    inferred_candidates: tuple[HeadingCandidate, ...],
    toc_result: Any | None,
    toc_reconciliation: Any | None,
    repair_engine: RepairEngine,
    gateway: StructuredLLMGateway | None,
) -> StrategyAttemptResult:
    attempt_root = _strategy_attempt_root(tree_root, attempt_index=attempt_index, strategy=strategy)
    toc_candidates = (
        toc_reconciliation.reconciled_candidates if toc_reconciliation is not None else ()
    )
    verification_assistant: LLMVerificationAssistant | None = None

    if strategy is HierarchyStrategy.OUTLINE_WITH_TOC_RECONCILIATION:
        trust_mode = determine_outline_trust_mode(
            selected_source=selected_source,
            outline_reports=outline_reports,
            outline_candidates=outline_candidates,
            inferred_candidates=inferred_candidates,
            toc_candidates=toc_candidates,
            settings=request.settings,
        )
        final_candidates = reconcile_heading_candidates(
            outline_candidates=outline_candidates,
            inferred_candidates=inferred_candidates,
            trust_mode=trust_mode,
            toc_candidates=toc_candidates,
            settings=request.settings,
        )
    elif strategy is HierarchyStrategy.OUTLINE_ONLY:
        trust_mode = OutlineTrustMode.OUTLINE_PRIMARY
        final_candidates = tuple(outline_candidates)
    elif strategy is HierarchyStrategy.TOC_DERIVED:
        trust_mode = OutlineTrustMode.TOC_RECONCILED
        final_candidates = tuple(candidate for candidate in toc_candidates if candidate.keep)
    elif strategy is HierarchyStrategy.INFERRED_WITH_LLM_ASSIST:
        trust_mode = OutlineTrustMode.INFERRED_PRIMARY
        final_candidates = tuple(candidate for candidate in inferred_candidates if candidate.keep)
        if gateway is not None:
            verification_assistant = LLMVerificationAssistant(
                gateway,
                artifact_root=str(attempt_root),
            )
    else:
        trust_mode = OutlineTrustMode.INFERRED_PRIMARY
        final_candidates = tuple(candidate for candidate in inferred_candidates if candidate.keep)

    gap_pages = _detect_explicit_gap_pages(pages, inferred_candidates)
    raw_nodes, repair_requests, ambiguity_count = build_hierarchy(
        document_id=document_id,
        candidates=final_candidates,
        page_count=page_count,
        trust_mode=trust_mode,
        gap_pages=gap_pages,
    )
    repaired_nodes = attach_default_owned_spans(raw_nodes, pages)
    repair_decisions = repair_engine.evaluate(repair_requests)
    if not repair_requests:
        repair_decisions = (
            RepairDecision(
                subject_id=document_id,
                status=RepairStatus.NOT_REQUESTED,
                message="no bounded repair requests were emitted by deterministic Phase 02 logic",
            ),
        )

    enriched_nodes = attach_content_anchors(repaired_nodes, pages)
    unassigned_spans = compute_unassigned_spans(
        document_id=document_id,
        page_count=page_count,
        nodes=enriched_nodes,
    )
    verified_nodes, verification_report = verify_hierarchy(
        document_id=document_id,
        tree_run_id=request.tree_run_id,
        page_count=page_count,
        nodes=enriched_nodes,
        pages=pages,
        unassigned_spans=unassigned_spans,
        settings=request.settings,
        verification_assistant=verification_assistant,
        outline_anchor_records=outline_anchor_records,
    )
    passed_ids = {
        result.subject_id
        for result in verification_report.node_results
        if result.status == VerificationStatus.PASSED
    }
    committed_nodes = tuple(node for node in verified_nodes if node.node_id in passed_ids)
    full_document_unassigned = _unassigned_page_count(unassigned_spans) == page_count
    node_cards = project_node_cards(committed_nodes)

    headings_path = write_json_file(
        attempt_root / "headings" / "candidates.json",
        {
            "strategy": strategy,
            "effective_trust_mode": trust_mode,
            "outline": outline_candidates,
            "outline_anchor_records": outline_anchor_records,
            "inferred": inferred_candidates,
            "toc": toc_candidates,
            "selected": final_candidates,
        },
    )
    raw_hierarchy_path = write_json_file(attempt_root / "hierarchy" / "raw.json", raw_nodes)
    repair_requests_path = write_json_file(
        attempt_root / "repair" / "requests.json",
        repair_requests,
    )
    repair_decisions_path = write_json_file(
        attempt_root / "repair" / "decisions.json", repair_decisions
    )
    repaired_hierarchy_path = write_json_file(
        attempt_root / "hierarchy" / "repaired.json",
        repaired_nodes,
    )
    committed_hierarchy_path = write_json_file(
        attempt_root / "hierarchy" / "committed.json",
        committed_nodes,
    )
    node_cards_path = write_json_file(attempt_root / "hierarchy" / "node-cards.json", node_cards)
    unassigned_spans_path = write_json_file(
        attempt_root / "unassigned-spans.json",
        unassigned_spans,
    )
    verification_report_path = write_json_file(
        attempt_root / "verify" / "report.json",
        verification_report,
    )
    build_report = HierarchyBuildReport(
        document_id=document_id,
        tree_run_id=request.tree_run_id,
        outline_trust_mode=trust_mode,
        candidate_count=len(final_candidates),
        outline_candidate_count=len(outline_candidates),
        inferred_candidate_count=len(inferred_candidates),
        selected_candidate_count=len(final_candidates),
        kept_candidate_count=sum(1 for candidate in final_candidates if candidate.keep),
        high_confidence_candidate_count=sum(
            1 for candidate in final_candidates if candidate.high_confidence
        ),
        candidates_with_layout_cues=sum(
            1 for candidate in final_candidates if candidate.score_breakdown.layout_cues_available
        ),
        candidates_without_layout_cues=sum(
            1
            for candidate in final_candidates
            if not candidate.score_breakdown.layout_cues_available
        ),
        committed_node_count=len(committed_nodes),
        unassigned_span_count=len(unassigned_spans),
        ambiguity_count=ambiguity_count,
        notes=(
            f"verification_status:{verification_report.status.value}",
            f"outline_trust_mode:{trust_mode.value}",
            f"strategy:{strategy.value}",
        ),
    )
    build_report_path = write_json_file(attempt_root / "build-report.json", build_report)
    toc_detection_path = None
    toc_reconciliation_path = None
    if toc_result is not None:
        toc_detection_path = write_json_file(attempt_root / "toc-detection.json", toc_result)
    if toc_reconciliation is not None:
        toc_reconciliation_path = write_json_file(
            attempt_root / "toc-reconciliation.json",
            toc_reconciliation,
        )

    return StrategyAttemptResult(
        strategy=strategy,
        artifact_root=str(attempt_root),
        committed_hierarchy_path=committed_hierarchy_path,
        node_cards_path=node_cards_path,
        verification_report_path=verification_report_path,
        headings_path=headings_path,
        raw_hierarchy_path=raw_hierarchy_path,
        repair_requests_path=repair_requests_path,
        repair_decisions_path=repair_decisions_path,
        repaired_hierarchy_path=repaired_hierarchy_path,
        unassigned_spans_path=unassigned_spans_path,
        build_report_path=build_report_path,
        committed_node_count=len(committed_nodes),
        unassigned_span_count=len(unassigned_spans),
        full_document_unassigned=full_document_unassigned,
        toc_detection_path=toc_detection_path,
        toc_reconciliation_path=toc_reconciliation_path,
        llm_verification_assists_path=(
            verification_assistant.artifact_path if verification_assistant is not None else None
        ),
    )


class TreePipelineService:
    """Deterministic Phase 02 hierarchy builder over persisted Phase 01 artifacts."""

    def __init__(
        self,
        *,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._logger = logger
        self._storage = storage

    def build(
        self,
        request: TreeBuildRequest,
        *,
        repair_engine: RepairEngine | None = None,
        gateway: StructuredLLMGateway | None = None,
    ) -> TreeBuildManifest:
        if request.summarize and gateway is None:
            raise TreePipelineError("summarize=True requires a configured gateway")

        input_store = build_document_store(self._storage, default_filesystem_root=".")
        input_bundle = _load_tree_input_bundle(request, store=input_store)
        tree_root: Path | None = (
            input_bundle.artifact_root / "tree" / request.tree_run_id
            if input_bundle.artifact_root is not None
            else None
        )
        registry_root = input_bundle.registry_root
        run_index_path = registry_root / request.tree_run_id / "run-index.json"
        digest = settings_digest(request.settings)
        output_store = build_document_store(
            self._storage,
            default_filesystem_root=str(tree_root) if tree_root is not None else None,
        )
        run_store = output_store.for_run(
            run_type="tree",
            run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
        )
        manifest_ref: str | None = run_store.artifact_ref("manifest.json")
        expected_identity = {
            "document_id": input_bundle.document_id,
            "registry_root": str(registry_root),
            "acquisition_manifest_path": input_bundle.manifest_path,
            "acquisition_artifact_identity": input_bundle.input_identity,
            "fingerprint_sha256": input_bundle.fingerprint_sha256,
            "settings_digest": digest,
        }
        run_index = TreeRunIndex(
            tree_run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
            registry_root=str(registry_root),
            acquisition_manifest_path=str(input_bundle.manifest_path),
            acquisition_artifact_identity=input_bundle.input_identity,
            acquisition_fingerprint_sha256=input_bundle.fingerprint_sha256,
            settings_digest=digest,
            manifest_path=manifest_ref,
        )

        if output_store.backend is StorageBackend.POSTGRES:
            created, run_record = output_store.reserve_run(
                run_type="tree",
                run_id=request.tree_run_id,
                document_id=input_bundle.document_id,
                artifact_root=None,
                identity=expected_identity,
            )
            if not created:
                if run_identity_matches(run_record, expected_identity):
                    manifest_ref = cast(
                        str | None,
                        run_record.get("manifest_ref") or run_record.get("manifest_path"),
                    )
                    if manifest_ref is None:
                        msg = "tree_run_id index points to a missing manifest"
                        raise TreePipelineError(msg)
                    return _load_tree_manifest_from_ref(output_store, manifest_ref)
                raise TreeConflictError(
                    "tree_run_id already exists with a different source manifest or settings",
                )
        elif run_index_path.exists():
            existing_index = _load_tree_run_index(run_index_path)
            existing_manifest_path = existing_index.manifest_path
            if (
                run_identity_matches(existing_index.model_dump(mode="json"), expected_identity)
                and existing_manifest_path is not None
                and Path(existing_manifest_path).exists()
            ):
                return _load_tree_manifest_from_ref(output_store, existing_manifest_path)
            raise TreeConflictError(
                "tree_run_id already exists with a different source manifest or settings",
            )
        pages = input_bundle.pages

        outline_candidates, outline_anchor_records = extract_outline_candidates_with_records(
            input_bundle.document_id,
            pages,
            input_bundle.outline_entries,
            settings=request.settings,
        )
        if input_bundle.outline_anchor_records:
            outline_anchor_records = input_bundle.outline_anchor_records
        inferred_candidates = extract_inferred_candidates(
            input_bundle.document_id,
            pages,
            input_bundle.outline_entries,
            request.settings,
        )
        base_trust_mode = determine_outline_trust_mode(
            selected_source=input_bundle.selected_source,
            outline_reports=input_bundle.outline_quality_reports,
            outline_candidates=outline_candidates,
            inferred_candidates=inferred_candidates,
            settings=request.settings,
        )
        engine = repair_engine or NoopRepairEngine()
        # Strategy attempts always use local filesystem even for Postgres backends.
        # When tree_root is None (Postgres mode), use a run-scoped temp path that
        # will be cleaned up after the run.
        effective_tree_root: Path = (
            tree_root if tree_root is not None else Path(f".tree_tmp/{request.tree_run_id}")
        )
        toc_detector = TocDetector(request.settings, gateway=gateway)
        toc_result = toc_detector.detect(pages=pages)
        toc_reconciliation = TocReconciler(request.settings, gateway=gateway).reconcile(
            document_id=input_bundle.document_id,
            pages=pages,
            toc_result=toc_result,
        )
        selected_attempt, strategy_report = execute_hierarchy_strategy(
            current_trust_mode=base_trust_mode,
            selected_outline_source=input_bundle.selected_source,
            toc_candidates=toc_reconciliation.reconciled_candidates,
            gateway_available=gateway is not None,
            attempt_runner=lambda strategy, attempt_index: _build_strategy_attempt(
                request=request,
                tree_root=effective_tree_root,
                attempt_index=attempt_index,
                strategy=strategy,
                document_id=input_bundle.document_id,
                page_count=input_bundle.page_count,
                selected_source=input_bundle.selected_source,
                outline_reports=input_bundle.outline_quality_reports,
                pages=pages,
                outline_candidates=outline_candidates,
                outline_anchor_records=outline_anchor_records,
                inferred_candidates=inferred_candidates,
                toc_result=toc_result,
                toc_reconciliation=toc_reconciliation,
                repair_engine=engine,
                gateway=gateway,
            ),
        )
        log_event(
            self._logger,
            "HierarchyStrategySelected",
            document_id=input_bundle.document_id,
            tree_run_id=request.tree_run_id,
            strategy=strategy_report.selected_strategy.value,
        )

        committed_nodes = _load_hierarchy_nodes(selected_attempt.committed_hierarchy_path)
        node_cards = project_node_cards(committed_nodes)
        decomposer = NodeDecomposer(request.settings, gateway=gateway)
        decomposed_nodes, decomposition_report = decomposer.decompose(
            nodes=committed_nodes,
            pages=pages,
            tree_run_id=request.tree_run_id,
            artifact_root=selected_attempt.artifact_root,
        )
        verification_report_payload: Any = _read_json(
            Path(selected_attempt.verification_report_path)
        )
        unassigned_spans_payload: Any = _read_json(Path(selected_attempt.unassigned_spans_path))
        build_report = _load_build_report(selected_attempt.build_report_path)
        committed_node_count = selected_attempt.committed_node_count
        unassigned_span_count = selected_attempt.unassigned_span_count
        llm_verification_assists_source = selected_attempt.llm_verification_assists_path
        node_summaries_payload = _load_node_summaries_payload(selected_attempt.node_summaries_path)

        if decomposition_report.decomposition_method is not DecompositionMethod.NONE:
            final_verification_assistant = (
                LLMVerificationAssistant(
                    gateway,
                    artifact_root=selected_attempt.artifact_root,
                )
                if gateway is not None
                else None
            )
            final_enriched_nodes = attach_content_anchors(decomposed_nodes, pages)
            final_unassigned_spans = compute_unassigned_spans(
                document_id=input_bundle.document_id,
                page_count=input_bundle.page_count,
                nodes=final_enriched_nodes,
            )
            final_verified_nodes, final_verification_report = verify_hierarchy(
                document_id=input_bundle.document_id,
                tree_run_id=request.tree_run_id,
                page_count=input_bundle.page_count,
                nodes=final_enriched_nodes,
                pages=pages,
                unassigned_spans=final_unassigned_spans,
                settings=request.settings,
                verification_assistant=final_verification_assistant,
                outline_anchor_records=outline_anchor_records,
            )
            passed_ids = {
                result.subject_id
                for result in final_verification_report.node_results
                if result.status == VerificationStatus.PASSED
            }
            committed_nodes = tuple(
                node for node in final_verified_nodes if node.node_id in passed_ids
            )
            node_cards = project_node_cards(committed_nodes)
            verification_report_payload = final_verification_report
            unassigned_spans_payload = final_unassigned_spans
            llm_verification_assists_source = (
                final_verification_assistant.artifact_path
                if final_verification_assistant is not None
                else llm_verification_assists_source
            )
            committed_node_count = len(committed_nodes)
            unassigned_span_count = len(final_unassigned_spans)
            build_report = build_report.model_copy(
                update={
                    "committed_node_count": committed_node_count,
                    "unassigned_span_count": unassigned_span_count,
                    "notes": (
                        *build_report.notes,
                        f"decomposition_method:{decomposition_report.decomposition_method.value}",
                        f"decomposition_depth:{decomposition_report.depth}",
                    ),
                }
            )

        if request.summarize:
            assert gateway is not None
            summarizer = NodeSummarizer(gateway, logger=self._logger)
            _, node_cards, node_summaries = summarizer.summarize(
                nodes=committed_nodes,
                pages=pages,
                artifact_root=selected_attempt.artifact_root,
            )
            node_summaries_payload = tuple(
                summary.model_dump(mode="json") for summary in node_summaries
            )

        headings_path = _persist_tree_json(
            run_store,
            artifact_kind="headings",
            artifact_path="headings/candidates.json",
            source_path=selected_attempt.headings_path,
        )
        raw_hierarchy_path = _persist_tree_json(
            run_store,
            artifact_kind="hierarchy",
            artifact_path="hierarchy/raw.json",
            source_path=selected_attempt.raw_hierarchy_path,
        )
        repair_requests_path = _persist_tree_json(
            run_store,
            artifact_kind="repair",
            artifact_path="repair/requests.json",
            source_path=selected_attempt.repair_requests_path,
        )
        repair_decisions_path = _persist_tree_json(
            run_store,
            artifact_kind="repair",
            artifact_path="repair/decisions.json",
            source_path=selected_attempt.repair_decisions_path,
        )
        repaired_hierarchy_path = _persist_tree_json(
            run_store,
            artifact_kind="hierarchy",
            artifact_path="hierarchy/repaired.json",
            source_path=selected_attempt.repaired_hierarchy_path,
        )
        committed_hierarchy_path = _persist_tree_json(
            run_store,
            artifact_kind="hierarchy",
            artifact_path="hierarchy/committed.json",
            payload=committed_nodes,
        )
        node_cards_path = _persist_tree_json(
            run_store,
            artifact_kind="node_cards",
            artifact_path="hierarchy/node-cards.json",
            payload=node_cards,
        )
        unassigned_spans_path = _persist_tree_json(
            run_store,
            artifact_kind="artifact",
            artifact_path="unassigned-spans.json",
            payload=unassigned_spans_payload,
        )
        verification_report_path = _persist_tree_json(
            run_store,
            artifact_kind="verification",
            artifact_path="verify/report.json",
            payload=verification_report_payload,
        )
        build_report_path = _persist_tree_json(
            run_store,
            artifact_kind="report",
            artifact_path="build-report.json",
            payload=build_report,
        )
        toc_detection_path = _persist_tree_json(
            run_store,
            artifact_kind="toc",
            artifact_path="toc-detection.json",
            source_path=selected_attempt.toc_detection_path,
        )
        toc_reconciliation_path = _persist_tree_json(
            run_store,
            artifact_kind="toc",
            artifact_path="toc-reconciliation.json",
            source_path=selected_attempt.toc_reconciliation_path,
        )
        llm_verification_assists_path = _persist_tree_json(
            run_store,
            artifact_kind="verification",
            artifact_path="verify/llm-assists.json",
            source_path=llm_verification_assists_source,
        )
        node_summaries_path = _persist_tree_json(
            run_store,
            artifact_kind="summary",
            artifact_path="summaries/node-summaries.json",
            payload=node_summaries_payload,
        )
        strategy_execution_report_path = _persist_tree_json(
            run_store,
            artifact_kind="report",
            artifact_path="strategy/execution-report.json",
            payload=strategy_report,
        )
        decomposition_report_path = _persist_tree_json(
            run_store,
            artifact_kind="report",
            artifact_path="decomposition/report.json",
            payload=decomposition_report,
        )

        self._emit_verification_events(
            document_id=input_bundle.document_id,
            tree_run_id=request.tree_run_id,
            verification_report_path=verification_report_path,
            committed_nodes=committed_nodes,
            store=output_store,
        )

        run_index_ref = _persist_tree_run_index(
            output_store,
            run_store,
            run_index_path=run_index_path,
            run_index=run_index,
        )
        manifest = TreeBuildManifest(
            tree_run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
            registry_root=str(registry_root),
            acquisition_manifest_path=input_bundle.manifest_path,
            acquisition_artifact_identity=input_bundle.input_identity,
            acquisition_fingerprint_sha256=input_bundle.fingerprint_sha256,
            artifact_root=_tree_manifest_artifact_root(
                backend=output_store.backend,
                tree_root=tree_root,
                run_id=request.tree_run_id,
                document_id=input_bundle.document_id,
            ),
            settings=request.settings,
            settings_digest=digest,
            run_index_path=run_index_ref,
            headings_path=headings_path,
            raw_hierarchy_path=raw_hierarchy_path,
            repair_requests_path=repair_requests_path,
            repair_decisions_path=repair_decisions_path,
            repaired_hierarchy_path=repaired_hierarchy_path,
            committed_hierarchy_path=committed_hierarchy_path,
            node_cards_path=node_cards_path,
            unassigned_spans_path=unassigned_spans_path,
            verification_report_path=verification_report_path,
            build_report_path=build_report_path,
            committed_node_count=committed_node_count,
            unassigned_span_count=unassigned_span_count,
            node_summaries_path=node_summaries_path,
            toc_detection_path=toc_detection_path,
            toc_reconciliation_path=toc_reconciliation_path,
            llm_verification_assists_path=llm_verification_assists_path,
            strategy_execution_report_path=strategy_execution_report_path,
            decomposition_report_path=decomposition_report_path,
        )
        manifest_ref = run_store.put_json(
            artifact_kind="manifest",
            artifact_path="manifest.json",
            payload=manifest,
        )
        _cleanup_attempt_artifacts(effective_tree_root)
        if output_store.backend is StorageBackend.POSTGRES:
            run_store.complete(
                manifest_ref=manifest_ref,
                manifest=manifest,
            )
        return manifest

    def _emit_verification_events(
        self,
        *,
        document_id: str,
        tree_run_id: str,
        verification_report_path: str | None,
        committed_nodes: tuple[HierarchyNode, ...],
        store: DocumentStore,
    ) -> None:
        if verification_report_path is None:
            for node in committed_nodes:
                log_event(
                    self._logger,
                    "NodeCommitted",
                    document_id=document_id,
                    tree_run_id=tree_run_id,
                    node_id=node.node_id,
                    title=node.title,
                )
            return
        verification_payload = cast(
            dict[str, Any], store.read_json_artifact(verification_report_path)
        )
        for node in committed_nodes:
            log_event(
                self._logger,
                "NodeCommitted",
                document_id=document_id,
                tree_run_id=tree_run_id,
                node_id=node.node_id,
                title=node.title,
            )
        for result in cast(list[dict[str, Any]], verification_payload.get("node_results", [])):
            if result.get("status") == VerificationStatus.PASSED.value:
                continue
            log_event(
                self._logger,
                "NodeVerificationFailed",
                document_id=document_id,
                tree_run_id=tree_run_id,
                subject_id=str(result["subject_id"]),
                issue_count=len(cast(list[dict[str, Any]], result.get("issues", []))),
            )


def build_tree(
    request: TreeBuildRequest,
    *,
    repair_engine: RepairEngine | None = None,
    gateway: StructuredLLMGateway | None = None,
    logger: Logger | None = None,
    storage: StorageConfig | None = None,
) -> TreeBuildManifest:
    """Build a deterministic tree from persisted acquisition artifacts."""

    return TreePipelineService(logger=logger, storage=storage).build(
        request,
        repair_engine=repair_engine,
        gateway=gateway,
    )


def build_tree_batch(
    requests: Sequence[TreeBuildRequest],
    *,
    storage: StorageConfig | None = None,
    gateway: StructuredLLMGateway | None = None,
    repair_engine: RepairEngine | None = None,
    max_workers: int = 4,
    logger: Logger | None = None,
) -> BatchResult[TreeBuildManifest]:
    """Build hierarchy trees for multiple documents concurrently.

    Each request is processed by a dedicated ``TreePipelineService`` in its
    own ``ThreadPoolExecutor`` worker thread to avoid shared mutable state.
    A failure in one document does not abort the batch; failed items are
    collected in ``BatchResult.failed``.

    Args:
        requests: Sequence of tree build requests to process.
        storage: Storage backend config shared by all workers.
        gateway: Optional structured LLM gateway for repair, verification,
            TOC detection, and summarization.
        repair_engine: Optional repair engine for hierarchy repair.
        max_workers: Thread-pool size.  Defaults to 4.
        logger: Optional logger propagated to every worker service instance.

    Returns:
        A ``BatchResult[TreeBuildManifest]`` with per-document outcomes.
    """
    successful: list[TreeBuildManifest] = []
    failed: list[BatchItemFailure] = []

    def _build_one(request: TreeBuildRequest) -> TreeBuildManifest:
        service = TreePipelineService(logger=logger, storage=storage)
        return service.build(request, gateway=gateway, repair_engine=repair_engine)

    futures: list[Future[TreeBuildManifest]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for req in requests:
            futures.append(executor.submit(_build_one, req))

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
