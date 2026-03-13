"""Artifact-driven Phase 02 tree pipeline orchestration."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from nullvector.domain.models import (
    AcquisitionRunManifest,
    CanonicalTextSubstrate,
    DecompositionMethod,
    HeadingCandidate,
    HierarchyBuildReport,
    HierarchyNode,
    HierarchyStrategy,
    OutlineAnchorRecord,
    OutlineEntry,
    OutlineQualityReport,
    OutlineSource,
    OutlineTrustMode,
    RepairDecision,
    RepairStatus,
    TitleMatchTier,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeRunIndex,
    VerificationStatus,
)
from nullvector.ingest.artifacts import canonical_json_bytes
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.observability import (
    EventBus,
    HierarchyStrategySelected,
    NodeCommitted,
    NodeVerificationFailed,
)
from nullvector.runtime_validation import validate_canonical_text_substrate_contract
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

    manifest_path: Path
    artifact_root: Path
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


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    return str(path)


def _settings_digest(request: TreeBuildRequest) -> str:
    return hashlib.sha256(canonical_json_bytes(request.settings)).hexdigest()


def _resolve_artifact_path(parse_root: Path, stored_path: str) -> Path:
    path = Path(stored_path)
    if path.is_absolute():
        return path
    if path.exists():
        return path.resolve()
    return parse_root / path


def _read_json(path: Path) -> Any:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_acquisition_manifest(acquisition_manifest_path: Path) -> AcquisitionRunManifest:
    return AcquisitionRunManifest.model_validate_json(
        acquisition_manifest_path.read_text(encoding="utf-8")
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
    acquisition_root: Path,
    acquisition_manifest: AcquisitionRunManifest,
) -> tuple[OutlineSource, tuple[OutlineEntry, ...]]:
    selected_outline_path = _resolve_artifact_path(
        acquisition_root, acquisition_manifest.selected_outline_path
    )
    payload = cast(dict[str, Any], _read_json(selected_outline_path))
    selected_source = OutlineSource(
        payload.get("selected_source", acquisition_manifest.selected_outline_source)
    )
    entries = tuple(
        OutlineEntry.model_validate({**entry, "source": OutlineSource(entry["source"])})
        for entry in cast(list[dict[str, Any]], payload.get("entries", []))
    )
    return selected_source, entries


def _load_canonical_text_substrate(
    acquisition_root: Path,
    acquisition_manifest: AcquisitionRunManifest,
) -> CanonicalTextSubstrate:
    try:
        substrate_path = validate_canonical_text_substrate_contract(
            acquisition_root=acquisition_root,
            manifest=acquisition_manifest,
        )
    except ValueError as exc:
        raise TreePipelineError(str(exc)) from exc
    return CanonicalTextSubstrate.model_validate_json(substrate_path.read_text(encoding="utf-8"))


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


def _load_tree_input_bundle(request: TreeBuildRequest) -> TreeInputBundle:
    acquisition_manifest_path = Path(request.acquisition_manifest_path).resolve()
    acquisition_manifest = _load_acquisition_manifest(acquisition_manifest_path)
    acquisition_root = acquisition_manifest_path.parent
    selected_source, outline_entries = _load_acquisition_outline_entries(
        acquisition_root, acquisition_manifest
    )
    text_substrate = _load_canonical_text_substrate(acquisition_root, acquisition_manifest)
    pages = _load_projection_page_artifacts(text_substrate)
    _, outline_anchor_records = extract_outline_candidates_with_records(
        acquisition_manifest.document_id,
        pages,
        outline_entries,
        settings=request.settings,
    )
    return TreeInputBundle(
        manifest_path=acquisition_manifest_path,
        artifact_root=acquisition_root,
        registry_root=_resolve_tree_registry_root(
            acquisition_root,
            input_run_id=acquisition_manifest.acquisition_run_id,
            document_id=acquisition_manifest.document_id,
        ),
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


def _accuracy_score(
    *,
    verified_nodes: tuple[HierarchyNode, ...],
    verification_report: Any,
) -> float:
    if not verification_report.node_results:
        return 0.0

    verified_by_id = {node.node_id: node for node in verified_nodes}
    total = len(verification_report.node_results)
    if total == 0:
        return 0.0

    weighted = 0.0
    for result in verification_report.node_results:
        node = verified_by_id.get(result.subject_id)
        if result.status != VerificationStatus.PASSED or node is None:
            continue

        match node.verification_match_tier:
            case TitleMatchTier.EXACT_NORMALIZED:
                weighted += 1.0
            case TitleMatchTier.CASEFOLD_PUNCT:
                weighted += 0.95
            case TitleMatchTier.TOKEN_CONTAINMENT:
                weighted += 0.75
            case TitleMatchTier.EDIT_DISTANCE:
                weighted += 0.60
            case TitleMatchTier.LLM_VERIFIED:
                weighted += 0.50
            case _:
                weighted += 0.0

    return weighted / total


def _unassigned_page_count(unassigned_spans: tuple[Any, ...]) -> int:
    """Return the number of pages represented by explicit unassigned spans."""

    return sum(span.page_span.end_page - span.page_span.start_page + 1 for span in unassigned_spans)


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
    accuracy = _accuracy_score(
        verified_nodes=verified_nodes,
        verification_report=verification_report,
    )
    if not committed_nodes:
        accuracy = 0.0
    if (
        verification_report.status != VerificationStatus.PASSED
        and _unassigned_page_count(unassigned_spans) == page_count
    ):
        accuracy = 0.0
    node_cards = project_node_cards(committed_nodes)

    headings_path = _write_json(
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
    raw_hierarchy_path = _write_json(attempt_root / "hierarchy" / "raw.json", raw_nodes)
    repair_requests_path = _write_json(attempt_root / "repair" / "requests.json", repair_requests)
    repair_decisions_path = _write_json(
        attempt_root / "repair" / "decisions.json", repair_decisions
    )
    repaired_hierarchy_path = _write_json(
        attempt_root / "hierarchy" / "repaired.json",
        repaired_nodes,
    )
    committed_hierarchy_path = _write_json(
        attempt_root / "hierarchy" / "committed.json",
        committed_nodes,
    )
    node_cards_path = _write_json(attempt_root / "hierarchy" / "node-cards.json", node_cards)
    unassigned_spans_path = _write_json(attempt_root / "unassigned-spans.json", unassigned_spans)
    verification_report_path = _write_json(
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
    build_report_path = _write_json(attempt_root / "build-report.json", build_report)
    toc_detection_path = None
    toc_reconciliation_path = None
    if toc_result is not None:
        toc_detection_path = _write_json(attempt_root / "toc-detection.json", toc_result)
    if toc_reconciliation is not None:
        toc_reconciliation_path = _write_json(
            attempt_root / "toc-reconciliation.json",
            toc_reconciliation,
        )

    return StrategyAttemptResult(
        strategy=strategy,
        accuracy=accuracy,
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
        toc_detection_path=toc_detection_path,
        toc_reconciliation_path=toc_reconciliation_path,
        llm_verification_assists_path=(
            verification_assistant.artifact_path if verification_assistant is not None else None
        ),
    )


class TreePipelineService:
    """Deterministic Phase 02 hierarchy builder over persisted Phase 01 artifacts."""

    def __init__(self, *, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus

    def build(
        self,
        request: TreeBuildRequest,
        *,
        repair_engine: RepairEngine | None = None,
        gateway: StructuredLLMGateway | None = None,
    ) -> TreeBuildManifest:
        if request.summarize and gateway is None:
            raise TreePipelineError("summarize=True requires a configured gateway")

        input_bundle = _load_tree_input_bundle(request)
        tree_root = input_bundle.artifact_root / "tree" / request.tree_run_id
        registry_root = input_bundle.registry_root
        run_index_path = registry_root / request.tree_run_id / "run-index.json"
        manifest_path = tree_root / "manifest.json"
        digest = _settings_digest(request)
        run_index = TreeRunIndex(
            tree_run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
            registry_root=str(registry_root),
            acquisition_manifest_path=str(input_bundle.manifest_path),
            acquisition_artifact_identity=input_bundle.input_identity,
            acquisition_fingerprint_sha256=input_bundle.fingerprint_sha256,
            settings_digest=digest,
            manifest_path=str(manifest_path),
        )

        if run_index_path.exists():
            existing_index = TreeRunIndex.model_validate_json(
                run_index_path.read_text(encoding="utf-8")
            )
            if (
                existing_index.registry_root == run_index.registry_root
                and existing_index.acquisition_artifact_identity
                == run_index.acquisition_artifact_identity
                and existing_index.acquisition_manifest_path == run_index.acquisition_manifest_path
                and existing_index.acquisition_fingerprint_sha256
                == run_index.acquisition_fingerprint_sha256
                and existing_index.settings_digest == run_index.settings_digest
                and Path(existing_index.manifest_path).exists()
            ):
                return TreeBuildManifest.model_validate_json(
                    Path(existing_index.manifest_path).read_text(encoding="utf-8"),
                )
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
            settings=request.settings,
            attempt_runner=lambda strategy, attempt_index: _build_strategy_attempt(
                request=request,
                tree_root=tree_root,
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
        strategy_execution_report_path = _write_json(
            tree_root / "strategy" / "execution-report.json",
            strategy_report,
        )
        if self._event_bus is not None:
            self._event_bus.publish(
                HierarchyStrategySelected(
                    event_id=f"{request.tree_run_id}-strategy",
                    event_name="HierarchyStrategySelected",
                    document_id=input_bundle.document_id,
                    tree_run_id=request.tree_run_id,
                    strategy=strategy_report.selected_strategy.value,
                )
            )

        committed_nodes = _load_hierarchy_nodes(selected_attempt.committed_hierarchy_path)
        decomposer = NodeDecomposer(request.settings, gateway=gateway)
        decomposed_nodes, decomposition_report = decomposer.decompose(
            nodes=committed_nodes,
            pages=pages,
            tree_run_id=request.tree_run_id,
            artifact_root=selected_attempt.artifact_root,
        )
        decomposition_report_path = decomposer.artifact_path
        verification_report_path = selected_attempt.verification_report_path
        committed_hierarchy_path = selected_attempt.committed_hierarchy_path
        node_cards_path = selected_attempt.node_cards_path
        unassigned_spans_path = selected_attempt.unassigned_spans_path
        build_report_path = selected_attempt.build_report_path
        committed_node_count = selected_attempt.committed_node_count
        unassigned_span_count = selected_attempt.unassigned_span_count
        llm_verification_assists_path = selected_attempt.llm_verification_assists_path

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
            committed_hierarchy_path = _write_json(
                Path(selected_attempt.committed_hierarchy_path),
                committed_nodes,
            )
            node_cards_path = _write_json(
                Path(selected_attempt.node_cards_path),
                project_node_cards(committed_nodes),
            )
            verification_report_path = _write_json(
                Path(selected_attempt.verification_report_path),
                final_verification_report,
            )
            unassigned_spans_path = _write_json(
                Path(selected_attempt.unassigned_spans_path),
                final_unassigned_spans,
            )
            llm_verification_assists_path = (
                final_verification_assistant.artifact_path
                if final_verification_assistant is not None
                else llm_verification_assists_path
            )
            committed_node_count = len(committed_nodes)
            unassigned_span_count = len(final_unassigned_spans)
            build_report = HierarchyBuildReport.model_validate_json(
                Path(selected_attempt.build_report_path).read_text(encoding="utf-8")
            )
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
            build_report_path = _write_json(
                Path(selected_attempt.build_report_path),
                build_report,
            )

        node_summaries_path = selected_attempt.node_summaries_path
        if request.summarize:
            assert gateway is not None
            summarizer = NodeSummarizer(gateway, event_bus=self._event_bus)
            _, node_cards, _ = summarizer.summarize(
                nodes=committed_nodes,
                pages=pages,
                artifact_root=selected_attempt.artifact_root,
            )
            node_cards_path = _write_json(
                Path(selected_attempt.artifact_root) / "hierarchy" / "node-cards.json",
                node_cards,
            )
            node_summaries_path = summarizer.artifact_path

        if self._event_bus is not None:
            self._emit_verification_events(
                document_id=input_bundle.document_id,
                tree_run_id=request.tree_run_id,
                verification_report_path=verification_report_path,
                committed_nodes=committed_nodes,
            )

        manifest = TreeBuildManifest(
            tree_run_id=request.tree_run_id,
            document_id=input_bundle.document_id,
            registry_root=str(registry_root),
            acquisition_manifest_path=str(input_bundle.manifest_path),
            acquisition_artifact_identity=input_bundle.input_identity,
            acquisition_fingerprint_sha256=input_bundle.fingerprint_sha256,
            artifact_root=str(tree_root),
            settings=request.settings,
            settings_digest=digest,
            run_index_path=str(run_index_path),
            headings_path=selected_attempt.headings_path,
            raw_hierarchy_path=selected_attempt.raw_hierarchy_path,
            repair_requests_path=selected_attempt.repair_requests_path,
            repair_decisions_path=selected_attempt.repair_decisions_path,
            repaired_hierarchy_path=selected_attempt.repaired_hierarchy_path,
            committed_hierarchy_path=committed_hierarchy_path,
            node_cards_path=node_cards_path,
            unassigned_spans_path=unassigned_spans_path,
            verification_report_path=verification_report_path,
            build_report_path=build_report_path,
            committed_node_count=committed_node_count,
            unassigned_span_count=unassigned_span_count,
            node_summaries_path=node_summaries_path,
            toc_detection_path=selected_attempt.toc_detection_path,
            toc_reconciliation_path=selected_attempt.toc_reconciliation_path,
            llm_verification_assists_path=llm_verification_assists_path,
            strategy_execution_report_path=strategy_execution_report_path,
            decomposition_report_path=decomposition_report_path,
        )
        _write_json(run_index_path, run_index)
        _write_json(manifest_path, manifest)
        return manifest

    def _emit_verification_events(
        self,
        *,
        document_id: str,
        tree_run_id: str,
        verification_report_path: str,
        committed_nodes: tuple[HierarchyNode, ...],
    ) -> None:
        if self._event_bus is None:
            return
        verification_payload = cast(dict[str, Any], _read_json(Path(verification_report_path)))
        for node in committed_nodes:
            self._event_bus.publish(
                NodeCommitted(
                    event_id=f"{tree_run_id}-{node.node_id}-committed",
                    event_name="NodeCommitted",
                    document_id=document_id,
                    tree_run_id=tree_run_id,
                    node_id=node.node_id,
                    title=node.title,
                )
            )
        for result in cast(list[dict[str, Any]], verification_payload.get("node_results", [])):
            if result.get("status") == VerificationStatus.PASSED.value:
                continue
            self._event_bus.publish(
                NodeVerificationFailed(
                    event_id=f"{tree_run_id}-{result['subject_id']}-verification-failed",
                    event_name="NodeVerificationFailed",
                    document_id=document_id,
                    tree_run_id=tree_run_id,
                    subject_id=str(result["subject_id"]),
                    issue_count=len(cast(list[dict[str, Any]], result.get("issues", []))),
                )
            )


def build_tree(
    request: TreeBuildRequest,
    *,
    repair_engine: RepairEngine | None = None,
    gateway: StructuredLLMGateway | None = None,
    event_bus: EventBus | None = None,
) -> TreeBuildManifest:
    """Build a deterministic tree from persisted acquisition artifacts."""

    return TreePipelineService(event_bus=event_bus).build(
        request,
        repair_engine=repair_engine,
        gateway=gateway,
    )
