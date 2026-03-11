"""Artifact-driven Phase 02 tree pipeline orchestration."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from strataforge.domain.models import (
    HeadingCandidate,
    HierarchyBuildReport,
    OutlineEntry,
    OutlineSource,
    PageLedgerRow,
    ParseRunManifest,
    RepairDecision,
    RepairStatus,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeRunIndex,
    VerificationStatus,
)
from strataforge.ingest.artifacts import canonical_json_bytes
from strataforge.tree.anchors import attach_content_anchors
from strataforge.tree.headings import (
    PageArtifacts,
    extract_inferred_candidates,
    extract_outline_candidates,
)
from strataforge.tree.hierarchy import (
    build_hierarchy,
    compute_unassigned_spans,
    determine_outline_trust_mode,
    project_node_cards,
    reconcile_heading_candidates,
)
from strataforge.tree.repair import NoopRepairEngine, RepairEngine
from strataforge.tree.verify import verify_hierarchy


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


class TreePipelineService:
    """Deterministic Phase 02 hierarchy builder over persisted Phase 01 artifacts."""

    def build(
        self,
        request: TreeBuildRequest,
        *,
        repair_engine: RepairEngine | None = None,
    ) -> TreeBuildManifest:
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
        trust_mode = determine_outline_trust_mode(
            selected_source=selected_source,
            outline_reports=parse_manifest.outline_quality_reports,
            outline_candidates=outline_candidates,
            inferred_candidates=inferred_candidates,
            settings=request.settings,
        )
        final_candidates = reconcile_heading_candidates(
            outline_candidates=outline_candidates,
            inferred_candidates=inferred_candidates,
            trust_mode=trust_mode,
            settings=request.settings,
        )
        gap_pages = _detect_explicit_gap_pages(pages, inferred_candidates)

        raw_nodes, repair_requests, ambiguity_count = build_hierarchy(
            document_id=parse_manifest.document_id,
            candidates=final_candidates,
            page_count=parse_manifest.page_count,
            trust_mode=trust_mode,
            gap_pages=gap_pages,
        )
        repaired_nodes = raw_nodes
        engine = repair_engine or NoopRepairEngine()
        repair_decisions = engine.evaluate(repair_requests)
        if not repair_requests:
            repair_decisions = (
                RepairDecision(
                    subject_id=parse_manifest.document_id,
                    status=RepairStatus.NOT_REQUESTED,
                    message=(
                        "no bounded repair requests were emitted by deterministic Phase 02 logic"
                    ),
                ),
            )

        enriched_nodes = attach_content_anchors(repaired_nodes, pages)
        unassigned_spans = compute_unassigned_spans(
            document_id=parse_manifest.document_id,
            page_count=parse_manifest.page_count,
            nodes=enriched_nodes,
        )
        verified_nodes, verification_report = verify_hierarchy(
            document_id=parse_manifest.document_id,
            tree_run_id=request.tree_run_id,
            page_count=parse_manifest.page_count,
            nodes=enriched_nodes,
            pages=pages,
            unassigned_spans=unassigned_spans,
            settings=request.settings,
        )
        passed_ids = {
            result.subject_id
            for result in verification_report.node_results
            if result.status == VerificationStatus.PASSED
        }
        committed_nodes = tuple(node for node in verified_nodes if node.node_id in passed_ids)
        node_cards = project_node_cards(committed_nodes)

        headings_path = _write_json(
            tree_root / "headings" / "candidates.json",
            {
                "outline": outline_candidates,
                "inferred": inferred_candidates,
                "selected": final_candidates,
            },
        )
        raw_hierarchy_path = _write_json(tree_root / "hierarchy" / "raw.json", raw_nodes)
        repair_requests_path = _write_json(tree_root / "repair" / "requests.json", repair_requests)
        repair_decisions_path = _write_json(
            tree_root / "repair" / "decisions.json", repair_decisions
        )
        repaired_hierarchy_path = _write_json(
            tree_root / "hierarchy" / "repaired.json",
            repaired_nodes,
        )
        committed_hierarchy_path = _write_json(
            tree_root / "hierarchy" / "committed.json",
            committed_nodes,
        )
        node_cards_path = _write_json(tree_root / "hierarchy" / "node-cards.json", node_cards)
        unassigned_spans_path = _write_json(
            tree_root / "unassigned-spans.json",
            unassigned_spans,
        )
        verification_report_path = _write_json(
            tree_root / "verify" / "report.json",
            verification_report,
        )
        build_report = HierarchyBuildReport(
            document_id=parse_manifest.document_id,
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
                1
                for candidate in final_candidates
                if candidate.score_breakdown.layout_cues_available
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
            ),
        )
        build_report_path = _write_json(tree_root / "build-report.json", build_report)

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
            committed_node_count=len(committed_nodes),
            unassigned_span_count=len(unassigned_spans),
        )
        _write_json(run_index_path, run_index)
        _write_json(manifest_path, manifest)
        return manifest


def build_tree(
    request: TreeBuildRequest,
    *,
    repair_engine: RepairEngine | None = None,
) -> TreeBuildManifest:
    """Build a deterministic tree from persisted Phase 01 artifacts."""

    return TreePipelineService().build(request, repair_engine=repair_engine)
