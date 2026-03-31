"""Focused unit tests for the Phase 2 tree service orchestration seams."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import BaseModel

from nullvector.domain.common import PageSourceAnchor, PageSpan, ScalarValue
from nullvector.domain.ledger import OutlineSource
from nullvector.domain.tree import (
    AnchorSource,
    DecompositionMethod,
    DecompositionReport,
    HierarchyBuildReport,
    HierarchyNode,
    HierarchyOrigin,
    HierarchyStrategy,
    NodeAnchor,
    OutlineTrustMode,
    StrategyExecutionReport,
    StrategyRationale,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeNodeVerificationResult,
    TreeRunIndex,
    TreeSettings,
    UnassignedPageSpan,
    VerificationReport,
    VerificationStatus,
)
from nullvector.runtime import RunContext
from nullvector.storage.filesystem import FilesystemDocumentStore
from nullvector.tree.headings import PageArtifacts
from nullvector.tree.service import (
    TreeInputBundle,
    TreePipelineService,
    _HierarchyPhaseResult,
)
from nullvector.tree.strategy import StrategyAttemptResult


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )


def _make_node(*, document_id: str, node_id: str, title: str) -> HierarchyNode:
    return HierarchyNode(
        node_id=node_id,
        document_id=document_id,
        path=(title,),
        level=1,
        title=title,
        normalized_title=title.casefold(),
        page_span=PageSpan(start_page=0, end_page=0),
        heading_anchor=NodeAnchor(
            page=0,
            start_offset=0,
            end_offset=len(title),
            anchor_text=title,
            anchor_source=AnchorSource.TEXT,
            occurrence_index=0,
        ),
        owned_spans=(),
        source_anchors=(
            PageSourceAnchor(
                page=0,
                start_offset=0,
                end_offset=len(title),
                quote=title,
            ),
        ),
        origin=HierarchyOrigin.INFERRED,
        confidence=1.0,
    )


def _make_tree_manifest(
    *,
    manifest_ref: str,
    run_index_path: str,
    acquisition_manifest_path: str,
    document_id: str,
) -> TreeBuildManifest:
    root = Path(manifest_ref).parent
    return TreeBuildManifest(
        tree_run_id="tree-run-001",
        document_id=document_id,
        registry_root=str(Path(run_index_path).parent.parent),
        acquisition_manifest_path=acquisition_manifest_path,
        acquisition_artifact_identity=acquisition_manifest_path,
        acquisition_fingerprint_sha256="b" * 64,
        artifact_root=str(root),
        settings=TreeSettings(),
        settings_digest="c" * 64,
        run_index_path=run_index_path,
        headings_path=str(root / "headings" / "candidates.json"),
        raw_hierarchy_path=str(root / "hierarchy" / "raw.json"),
        repair_requests_path=str(root / "repair" / "requests.json"),
        repair_decisions_path=str(root / "repair" / "decisions.json"),
        repaired_hierarchy_path=str(root / "hierarchy" / "repaired.json"),
        committed_hierarchy_path=str(root / "hierarchy" / "committed.json"),
        node_cards_path=str(root / "hierarchy" / "node-cards.json"),
        unassigned_spans_path=str(root / "unassigned-spans.json"),
        verification_report_path=str(root / "verify" / "report.json"),
        build_report_path=str(root / "build-report.json"),
        committed_node_count=1,
        unassigned_span_count=0,
    )


def test_reserve_or_reuse_returns_existing_manifest_for_matching_filesystem_run(
    tmp_path: Path,
) -> None:
    service = TreePipelineService(logger=logging.getLogger("tree-phase2-test"))
    document_id = "a" * 64
    artifact_root = tmp_path / "tree" / "tree-run-001" / document_id
    store = FilesystemDocumentStore(str(artifact_root))
    ctx = RunContext(
        store=store,
        run_store=store.for_run(
            run_type="tree",
            run_id="tree-run-001",
            document_id=document_id,
        ),
        artifact_root=str(artifact_root),
        logger=logging.getLogger("tree-phase2-test"),
    )
    request = TreeBuildRequest(
        acquisition_manifest_path=str(tmp_path / "acquisition" / "manifest.json"),
        tree_run_id="tree-run-001",
    )
    run_index_path = tmp_path / "_tree_runs" / "tree-run-001" / "run-index.json"
    expected_identity: dict[str, ScalarValue] = {
        "document_id": document_id,
        "registry_root": str(tmp_path / "_tree_runs"),
        "acquisition_manifest_path": request.acquisition_manifest_path,
        "acquisition_artifact_identity": request.acquisition_manifest_path,
        "fingerprint_sha256": "b" * 64,
        "settings_digest": "c" * 64,
    }
    manifest = _make_tree_manifest(
        manifest_ref=ctx.run_store.artifact_ref("manifest.json"),
        run_index_path=str(run_index_path),
        acquisition_manifest_path=request.acquisition_manifest_path,
        document_id=document_id,
    )
    manifest_ref = ctx.run_store.put_json(
        artifact_kind="manifest",
        artifact_path="manifest.json",
        payload=manifest,
    )
    run_index = TreeRunIndex(
        tree_run_id=request.tree_run_id,
        document_id=document_id,
        registry_root=str(tmp_path / "_tree_runs"),
        acquisition_manifest_path=request.acquisition_manifest_path,
        acquisition_artifact_identity=request.acquisition_manifest_path,
        acquisition_fingerprint_sha256="b" * 64,
        settings_digest="c" * 64,
        manifest_path=manifest_ref,
    )
    _write_json(run_index_path, run_index)

    reused = service._reserve_or_reuse(
        ctx,
        request,
        expected_identity,
        run_index_path,
        run_index,
    )

    assert reused == manifest


def test_run_verification_and_summarization_uses_decomposition_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = TreePipelineService(logger=logging.getLogger("tree-phase2-test"))
    document_id = "d" * 64
    store = FilesystemDocumentStore(str(tmp_path / "tree-runtime"))
    ctx = RunContext(
        store=store,
        run_store=store.for_run(
            run_type="tree",
            run_id="tree-run-002",
            document_id=document_id,
        ),
        artifact_root=str(tmp_path / "tree-runtime"),
        logger=logging.getLogger("tree-phase2-test"),
    )
    request = TreeBuildRequest(
        acquisition_manifest_path=str(tmp_path / "acquisition" / "manifest.json"),
        tree_run_id="tree-run-002",
    )
    input_bundle = TreeInputBundle(
        manifest_path=request.acquisition_manifest_path,
        artifact_root=None,
        registry_root=tmp_path / "_tree_runs",
        document_id=document_id,
        page_count=1,
        input_identity=request.acquisition_manifest_path,
        fingerprint_sha256="e" * 64,
        selected_source=OutlineSource.NONE,
        outline_entries=(),
        outline_anchor_records=(),
        outline_quality_reports=(),
        pages=(PageArtifacts(page_index=0, text="Original\nReplacement", rawdict=None),),
    )
    original_node = _make_node(document_id=document_id, node_id="1" * 64, title="Original")
    replacement_node = _make_node(
        document_id=document_id,
        node_id="2" * 64,
        title="Replacement",
    )
    selected_attempt = StrategyAttemptResult(
        strategy=HierarchyStrategy.INFERRED_DETERMINISTIC,
        artifact_root=str(tmp_path / "attempt"),
        committed_hierarchy_path=str(tmp_path / "attempt" / "committed.json"),
        node_cards_path=str(tmp_path / "attempt" / "node-cards.json"),
        verification_report_path=str(tmp_path / "attempt" / "verification-report.json"),
        headings_path=str(tmp_path / "attempt" / "headings.json"),
        raw_hierarchy_path=str(tmp_path / "attempt" / "raw-hierarchy.json"),
        repair_requests_path=str(tmp_path / "attempt" / "repair-requests.json"),
        repair_decisions_path=str(tmp_path / "attempt" / "repair-decisions.json"),
        repaired_hierarchy_path=str(tmp_path / "attempt" / "repaired-hierarchy.json"),
        unassigned_spans_path=str(tmp_path / "attempt" / "unassigned-spans.json"),
        build_report_path=str(tmp_path / "attempt" / "build-report.json"),
        committed_node_count=1,
        unassigned_span_count=0,
        full_document_unassigned=False,
    )
    initial_report = VerificationReport(
        document_id=document_id,
        tree_run_id=request.tree_run_id,
        status=VerificationStatus.PASSED,
    )
    build_report = HierarchyBuildReport(
        document_id=document_id,
        tree_run_id=request.tree_run_id,
        outline_trust_mode=OutlineTrustMode.INFERRED_PRIMARY,
        candidate_count=1,
        outline_candidate_count=0,
        inferred_candidate_count=1,
        selected_candidate_count=1,
        kept_candidate_count=1,
        high_confidence_candidate_count=1,
        candidates_with_layout_cues=0,
        candidates_without_layout_cues=1,
        committed_node_count=1,
        unassigned_span_count=0,
        ambiguity_count=0,
    )
    _write_json(Path(selected_attempt.verification_report_path), initial_report)
    _write_json(Path(selected_attempt.unassigned_spans_path), ())
    _write_json(Path(selected_attempt.build_report_path), build_report)
    hierarchy_result = _HierarchyPhaseResult(
        selected_attempt=selected_attempt,
        strategy_report=StrategyExecutionReport(
            attempted_strategies=(HierarchyStrategy.INFERRED_DETERMINISTIC,),
            selected_strategy=HierarchyStrategy.INFERRED_DETERMINISTIC,
            rationale=StrategyRationale(
                reasons=("test",),
                outline_available=False,
                toc_available=False,
                gateway_available=False,
            ),
        ),
        committed_nodes=(original_node,),
        outline_anchor_records=(),
    )
    final_unassigned = (
        UnassignedPageSpan(
            document_id=document_id,
            reason="gap_after_decomposition",
            page_span=PageSpan(start_page=0, end_page=0),
        ),
    )
    final_report = VerificationReport(
        document_id=document_id,
        tree_run_id=request.tree_run_id,
        status=VerificationStatus.PASSED,
        node_results=(
            TreeNodeVerificationResult(
                document_id=document_id,
                tree_run_id=request.tree_run_id,
                subject_id=replacement_node.node_id,
                status=VerificationStatus.PASSED,
                covered_page_span=PageSpan(start_page=0, end_page=0),
            ),
        ),
    )

    def fake_decompose(
        self: object,
        *,
        nodes: tuple[HierarchyNode, ...],
        pages: tuple[PageArtifacts, ...],
        tree_run_id: str,
        artifact_root: str,
    ) -> tuple[tuple[HierarchyNode, ...], DecompositionReport]:
        del self, pages, tree_run_id, artifact_root
        assert nodes == (original_node,)
        return (
            (replacement_node,),
            DecompositionReport(
                decomposition_method=DecompositionMethod.DETERMINISTIC,
                decomposed_node_ids=(original_node.node_id,),
                new_child_count=1,
                depth=2,
            ),
        )

    monkeypatch.setattr(
        "nullvector.tree.service.NodeDecomposer.decompose",
        fake_decompose,
    )
    monkeypatch.setattr(
        "nullvector.tree.service.attach_content_anchors",
        lambda nodes, pages: nodes,
    )
    monkeypatch.setattr(
        "nullvector.tree.service.compute_unassigned_spans",
        lambda **_: final_unassigned,
    )
    monkeypatch.setattr(
        "nullvector.tree.service.verify_hierarchy",
        lambda **_: ((replacement_node,), final_report),
    )

    result = service._run_verification_and_summarization(
        ctx,
        request,
        input_bundle,
        hierarchy_result,
        gateway=None,
    )

    assert result.committed_nodes == (replacement_node,)
    assert result.node_cards[0].node_id == replacement_node.node_id
    assert result.committed_node_count == 1
    assert result.unassigned_span_count == 1
    assert result.decomposition_report.decomposition_method is DecompositionMethod.DETERMINISTIC
    assert "decomposition_method:deterministic" in result.build_report.notes
    assert "decomposition_depth:2" in result.build_report.notes
