"""Artifact-driven Phase 02 tree pipeline orchestration."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from strataforge.domain.models import (
    DecompositionMethod,
    HeadingCandidate,
    HierarchyBuildReport,
    HierarchyNode,
    HierarchyStrategy,
    OutlineEntry,
    OutlineSource,
    OutlineTrustMode,
    PageLedgerRow,
    ParseRunManifest,
    RepairDecision,
    RepairStatus,
    TitleMatchTier,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeRunIndex,
    VerificationStatus,
)
from strataforge.ingest.artifacts import canonical_json_bytes
from strataforge.llm.protocols import StructuredLLMGateway
from strataforge.tree.anchors import attach_content_anchors
from strataforge.tree.decompose import NodeDecomposer
from strataforge.tree.headings import (
    PageArtifacts,
    extract_inferred_candidates,
    extract_outline_candidates,
)
from strataforge.tree.hierarchy import (
    attach_default_owned_spans,
    build_hierarchy,
    compute_unassigned_spans,
    determine_outline_trust_mode,
    project_node_cards,
    reconcile_heading_candidates,
)
from strataforge.tree.repair import NoopRepairEngine, RepairEngine
from strataforge.tree.strategy import (
    StrategyAttemptResult,
    execute_hierarchy_strategy,
)
from strataforge.tree.summarize import NodeSummarizer
from strataforge.tree.toc import TocDetector
from strataforge.tree.toc_reconcile import TocReconciler
from strataforge.tree.verify import LLMVerificationAssistant, verify_hierarchy


class TreePipelineError(Exception):
    """Base class for deterministic Phase 02 tree build failures."""


class TreeConflictError(TreePipelineError):
    """Raised when a tree run id is reused with different effective inputs."""


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
    return path if path.is_absolute() else parse_root / path


def _read_json(path: Path) -> Any:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_parse_manifest(parse_manifest_path: Path) -> ParseRunManifest:
    return ParseRunManifest.model_validate_json(parse_manifest_path.read_text(encoding="utf-8"))


def _resolve_tree_registry_root(
    parse_manifest_path: Path,
    parse_manifest: ParseRunManifest,
) -> Path:
    parse_root = parse_manifest_path.parent
    if (
        parse_root.name == parse_manifest.document_id
        and parse_root.parent.name == parse_manifest.parse_run_id
    ):
        return parse_root.parent.parent / "_tree_runs"
    return parse_root.parent / "_tree_runs"


def _load_outline_entries(
    parse_root: Path, parse_manifest: ParseRunManifest
) -> tuple[OutlineSource, tuple[OutlineEntry, ...]]:
    selected_outline_path = _resolve_artifact_path(parse_root, parse_manifest.selected_outline_path)
    payload = cast(dict[str, Any], _read_json(selected_outline_path))
    selected_source = OutlineSource(
        payload.get("selected_source", parse_manifest.selected_outline_source)
    )
    entries = tuple(
        OutlineEntry.model_validate({**entry, "source": OutlineSource(entry["source"])})
        for entry in cast(list[dict[str, Any]], payload.get("entries", []))
    )
    return selected_source, entries


def _load_ledger_rows(
    parse_root: Path, parse_manifest: ParseRunManifest
) -> tuple[PageLedgerRow, ...]:
    ledger_path = _resolve_artifact_path(parse_root, parse_manifest.ledger_path)
    rows: list[PageLedgerRow] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(PageLedgerRow.model_validate_json(line))
    return tuple(rows)


def _load_page_artifacts(
    parse_root: Path, ledger_rows: tuple[PageLedgerRow, ...]
) -> tuple[PageArtifacts, ...]:
    pages: list[PageArtifacts] = []
    for row in sorted(ledger_rows, key=lambda item: item.page_index):
        text_path = _resolve_artifact_path(parse_root, row.text_artifact_path)
        rawdict_path_value = row.ocr_rawdict_artifact_path or row.native_rawdict_artifact_path
        rawdict = None
        if rawdict_path_value is not None:
            rawdict = cast(
                dict[str, Any], _read_json(_resolve_artifact_path(parse_root, rawdict_path_value))
            )
        pages.append(
            PageArtifacts(
                page_index=row.page_index,
                text=text_path.read_text(encoding="utf-8"),
                rawdict=rawdict,
                page_label=row.page_label,
            ),
        )
    return tuple(pages)


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

    def build(
        self,
        request: TreeBuildRequest,
        *,
        repair_engine: RepairEngine | None = None,
        gateway: StructuredLLMGateway | None = None,
    ) -> TreeBuildManifest:
        if request.summarize and gateway is None:
            raise TreePipelineError("summarize=True requires a configured gateway")

        parse_manifest_path = Path(request.parse_manifest_path).resolve()
        parse_manifest = _load_parse_manifest(parse_manifest_path)
        parse_root = parse_manifest_path.parent
        tree_root = parse_root / "tree" / request.tree_run_id
        registry_root = _resolve_tree_registry_root(parse_manifest_path, parse_manifest)
        run_index_path = registry_root / request.tree_run_id / "run-index.json"
        manifest_path = tree_root / "manifest.json"
        digest = _settings_digest(request)
        parse_artifact_identity = str(parse_manifest_path)
        run_index = TreeRunIndex(
            tree_run_id=request.tree_run_id,
            document_id=parse_manifest.document_id,
            registry_root=str(registry_root),
            parse_manifest_path=str(parse_manifest_path),
            parse_artifact_identity=parse_artifact_identity,
            parse_fingerprint_sha256=parse_manifest.fingerprint.sha256,
            settings_digest=digest,
            manifest_path=str(manifest_path),
        )

        if run_index_path.exists():
            existing_index = TreeRunIndex.model_validate_json(
                run_index_path.read_text(encoding="utf-8")
            )
            if (
                existing_index.registry_root == run_index.registry_root
                and existing_index.parse_artifact_identity == run_index.parse_artifact_identity
                and existing_index.parse_manifest_path == run_index.parse_manifest_path
                and existing_index.parse_fingerprint_sha256 == run_index.parse_fingerprint_sha256
                and existing_index.settings_digest == run_index.settings_digest
                and Path(existing_index.manifest_path).exists()
            ):
                return TreeBuildManifest.model_validate_json(
                    Path(existing_index.manifest_path).read_text(encoding="utf-8"),
                )
            raise TreeConflictError(
                "tree_run_id already exists with a different parse manifest or settings",
            )

        selected_source, outline_entries = _load_outline_entries(parse_root, parse_manifest)
        ledger_rows = _load_ledger_rows(parse_root, parse_manifest)
        pages = _load_page_artifacts(parse_root, ledger_rows)

        outline_candidates = extract_outline_candidates(
            parse_manifest.document_id,
            pages,
            outline_entries,
        )
        inferred_candidates = extract_inferred_candidates(
            parse_manifest.document_id,
            pages,
            outline_entries,
            request.settings,
        )
        base_trust_mode = determine_outline_trust_mode(
            selected_source=selected_source,
            outline_reports=parse_manifest.outline_quality_reports,
            outline_candidates=outline_candidates,
            inferred_candidates=inferred_candidates,
            settings=request.settings,
        )
        engine = repair_engine or NoopRepairEngine()
        toc_detector = TocDetector(request.settings, gateway=gateway)
        toc_result = toc_detector.detect(pages=pages)
        toc_reconciliation = TocReconciler(request.settings, gateway=gateway).reconcile(
            document_id=parse_manifest.document_id,
            pages=pages,
            toc_result=toc_result,
        )
        selected_attempt, strategy_report = execute_hierarchy_strategy(
            current_trust_mode=base_trust_mode,
            selected_outline_source=selected_source,
            toc_candidates=toc_reconciliation.reconciled_candidates,
            gateway_available=gateway is not None,
            settings=request.settings,
            attempt_runner=lambda strategy, attempt_index: _build_strategy_attempt(
                request=request,
                tree_root=tree_root,
                attempt_index=attempt_index,
                strategy=strategy,
                document_id=parse_manifest.document_id,
                page_count=parse_manifest.page_count,
                selected_source=selected_source,
                outline_reports=tuple(parse_manifest.outline_quality_reports),
                pages=pages,
                outline_candidates=outline_candidates,
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
                document_id=parse_manifest.document_id,
                page_count=parse_manifest.page_count,
                nodes=final_enriched_nodes,
            )
            final_verified_nodes, final_verification_report = verify_hierarchy(
                document_id=parse_manifest.document_id,
                tree_run_id=request.tree_run_id,
                page_count=parse_manifest.page_count,
                nodes=final_enriched_nodes,
                pages=pages,
                unassigned_spans=final_unassigned_spans,
                settings=request.settings,
                verification_assistant=final_verification_assistant,
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
            summarizer = NodeSummarizer(gateway)
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

        manifest = TreeBuildManifest(
            tree_run_id=request.tree_run_id,
            document_id=parse_manifest.document_id,
            registry_root=str(registry_root),
            parse_manifest_path=str(parse_manifest_path),
            parse_artifact_identity=parse_artifact_identity,
            parse_fingerprint_sha256=parse_manifest.fingerprint.sha256,
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


def build_tree(
    request: TreeBuildRequest,
    *,
    repair_engine: RepairEngine | None = None,
    gateway: StructuredLLMGateway | None = None,
) -> TreeBuildManifest:
    """Build a deterministic tree from persisted Phase 01 artifacts."""

    return TreePipelineService().build(request, repair_engine=repair_engine, gateway=gateway)
