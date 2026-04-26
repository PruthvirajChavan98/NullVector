"""Unit coverage for serving-tree compaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullvector.domain.common import ContentSpan, NodeOwnedSpan, PageSourceAnchor, PageSpan
from nullvector.domain.tree import (
    HierarchyNode,
    HierarchyOrigin,
    NodeCard,
    NodeSummary,
    NodeSummaryMethod,
    TreeBuildManifest,
    TreeCompactionRequest,
    TreeCompactionSettings,
    TreeSettings,
)
from nullvector.storage._serialization import settings_digest
from nullvector.tree import (
    TreeCompactionService,
    expand_serving_node_ids_to_canonical_node_ids,
    load_compacted_node_mappings,
    load_compacted_tree,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump"):
        serializable = payload.model_dump(mode="json")
    elif isinstance(payload, tuple):
        serializable = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in payload
        ]
    else:
        serializable = payload
    path.write_text(
        json.dumps(serializable, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )


def _hierarchy_node(
    *,
    node_id: str,
    title: str,
    path: tuple[str, ...],
    level: int,
    start_page: int,
    end_page: int,
    parent_id: str | None = None,
) -> HierarchyNode:
    return HierarchyNode(
        node_id=node_id,
        document_id="a" * 64,
        parent_id=parent_id,
        path=path,
        level=level,
        title=title,
        normalized_title=title.casefold(),
        page_span=PageSpan(start_page=start_page, end_page=end_page),
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=start_page,
                    start_offset=0,
                    end_page=end_page,
                    end_offset=max(len(title), 16),
                ),
            ),
        ),
        source_anchors=(
            PageSourceAnchor(
                page=start_page,
                start_offset=0,
                end_offset=min(len(title), 16),
                quote=title[:16],
            ),
        ),
        origin=HierarchyOrigin.INFERRED,
        confidence=1.0,
    )


def _node_card(node: HierarchyNode) -> NodeCard:
    return NodeCard(
        node_id=node.node_id,
        document_id=node.document_id,
        path=node.path,
        level=node.level,
        title=node.title,
        page_span=node.page_span,
        owned_spans=node.owned_spans,
        source_anchors=node.source_anchors,
    )


def _node_summary(node_id: str, summary: str) -> NodeSummary:
    return NodeSummary(
        node_id=node_id,
        summary=summary,
        keywords=(summary.split()[0].casefold(),),
        summary_method=NodeSummaryMethod.PASSTHROUGH,
        token_count=8,
        estimated_token_count=8,
        exact_token_count=8,
        tokenizer_identity="synthetic",
    )


def _write_tree_fixture(
    tmp_path: Path,
    *,
    child_ids: tuple[str, ...],
    child_summaries: frozenset[str] = frozenset(),
    branch_child_id: str | None = None,
) -> Path:
    tree_root = tmp_path / "tree-fixture"
    root_node = _hierarchy_node(
        node_id="root",
        title="Root",
        path=("Root",),
        level=1,
        start_page=0,
        end_page=max(len(child_ids), 1),
    )
    nodes: list[HierarchyNode] = [root_node]
    for page_index, child_id in enumerate(child_ids, start=1):
        nodes.append(
            _hierarchy_node(
                node_id=child_id,
                title=child_id.title(),
                path=("Root", child_id.title()),
                level=2,
                start_page=page_index,
                end_page=page_index,
                parent_id="root",
            )
        )
    if branch_child_id is not None:
        nodes.append(
            _hierarchy_node(
                node_id=f"{branch_child_id}-detail",
                title=f"{branch_child_id.title()} Detail",
                path=("Root", branch_child_id.title(), f"{branch_child_id.title()} Detail"),
                level=3,
                start_page=2,
                end_page=2,
                parent_id=branch_child_id,
            )
        )

    cards = tuple(_node_card(node) for node in nodes)
    summaries = [_node_summary("root", "Root summary.")]
    for child_id in child_ids:
        if child_id in child_summaries:
            summaries.append(_node_summary(child_id, f"{child_id.title()} summary."))
    if branch_child_id is not None:
        summaries.append(_node_summary(f"{branch_child_id}-detail", "Detail summary."))

    committed_path = tree_root / "canonical" / "committed.json"
    node_cards_path = tree_root / "canonical" / "node-cards.json"
    node_summaries_path = tree_root / "canonical" / "node-summaries.json"
    manifest_path = tree_root / "manifest.json"
    _write_json(committed_path, tuple(nodes))
    _write_json(node_cards_path, cards)
    _write_json(node_summaries_path, tuple(summaries))

    settings = TreeSettings()
    manifest = TreeBuildManifest(
        tree_run_id="tree-run",
        document_id="a" * 64,
        registry_root=str(tree_root / "_registry"),
        acquisition_manifest_path=str(tree_root / "acquisition-manifest.json"),
        acquisition_artifact_identity=str(tree_root / "acquisition-manifest.json"),
        acquisition_fingerprint_sha256="a" * 64,
        artifact_root=str(tree_root),
        settings=settings,
        settings_digest=settings_digest(settings),
        run_index_path=str(tree_root / "run-index.json"),
        committed_hierarchy_path=str(committed_path),
        node_cards_path=str(node_cards_path),
        node_summaries_path=str(node_summaries_path),
        committed_node_count=len(nodes),
        unassigned_span_count=0,
    )
    _write_json(manifest_path, manifest)
    return manifest_path


def test_compaction_keeps_high_signal_children_on_mild_overflow(tmp_path: Path) -> None:
    manifest_path = _write_tree_fixture(
        tmp_path,
        child_ids=("alpha", "beta", "gamma"),
        child_summaries=frozenset({"alpha"}),
        branch_child_id="beta",
    )

    manifest = TreeCompactionService().compact(
        TreeCompactionRequest(
            tree_manifest_path=str(manifest_path),
            compaction_run_id="mild-overflow",
            settings=TreeCompactionSettings(max_children_per_node=2, require_summaries=False),
        )
    )

    compacted_tree = load_compacted_tree(manifest.compacted_tree_path)
    root_node = next(node for node in compacted_tree if node.serving_node_id == "root")

    assert root_node.child_serving_node_ids == ("alpha", "beta", "root::compact::03")


def test_compaction_pathological_width_enforces_hard_cap(tmp_path: Path) -> None:
    manifest_path = _write_tree_fixture(
        tmp_path,
        child_ids=("alpha", "beta", "gamma", "delta", "epsilon"),
        child_summaries=frozenset({"alpha"}),
    )

    manifest = TreeCompactionService().compact(
        TreeCompactionRequest(
            tree_manifest_path=str(manifest_path),
            compaction_run_id="pathological-overflow",
            settings=TreeCompactionSettings(max_children_per_node=2, require_summaries=False),
        )
    )

    compacted_tree = load_compacted_tree(manifest.compacted_tree_path)
    root_node = next(node for node in compacted_tree if node.serving_node_id == "root")

    assert len(root_node.child_serving_node_ids) <= 2


def test_merged_node_mapping_preserves_document_order(tmp_path: Path) -> None:
    manifest_path = _write_tree_fixture(
        tmp_path,
        child_ids=("alpha", "beta", "gamma", "delta", "epsilon"),
        child_summaries=frozenset({"alpha", "beta", "gamma", "delta", "epsilon"}),
    )

    manifest = TreeCompactionService().compact(
        TreeCompactionRequest(
            tree_manifest_path=str(manifest_path),
            compaction_run_id="mapping-order",
            settings=TreeCompactionSettings(max_children_per_node=2, require_summaries=True),
        )
    )

    compacted_tree = load_compacted_tree(manifest.compacted_tree_path)
    merged_node = next(
        node for node in compacted_tree if node.serving_node_id.startswith("root::compact::")
    )

    assert len(merged_node.canonical_node_ids) > 1
    assert merged_node.canonical_node_ids == tuple(
        sorted(
            merged_node.canonical_node_ids,
            key=lambda node_id: ("alpha", "beta", "gamma", "delta", "epsilon").index(node_id),
        )
    )


def test_compaction_requires_summaries_for_merged_nodes_by_default(tmp_path: Path) -> None:
    manifest_path = _write_tree_fixture(
        tmp_path,
        child_ids=("alpha", "beta", "gamma"),
        child_summaries=frozenset({"alpha"}),
        branch_child_id="alpha",
    )

    with pytest.raises(ValueError, match="requires summaries for merged serving nodes"):
        TreeCompactionService().compact(
            TreeCompactionRequest(
                tree_manifest_path=str(manifest_path),
                compaction_run_id="missing-summaries",
                settings=TreeCompactionSettings(max_children_per_node=2),
            )
        )


def test_expand_serving_node_ids_returns_ordered_deduplicated_canonical_ids(tmp_path: Path) -> None:
    manifest_path = _write_tree_fixture(
        tmp_path,
        child_ids=("alpha", "beta", "gamma", "delta", "epsilon"),
        child_summaries=frozenset({"alpha", "beta", "gamma", "delta", "epsilon"}),
    )

    manifest = TreeCompactionService().compact(
        TreeCompactionRequest(
            tree_manifest_path=str(manifest_path),
            compaction_run_id="expand-mapping",
            settings=TreeCompactionSettings(max_children_per_node=2),
        )
    )

    mappings = load_compacted_node_mappings(manifest.node_mapping_path)
    compacted_tree = load_compacted_tree(manifest.compacted_tree_path)
    root_node = next(node for node in compacted_tree if node.serving_node_id == "root")
    expanded = expand_serving_node_ids_to_canonical_node_ids(
        root_node.child_serving_node_ids + root_node.child_serving_node_ids,
        mappings,
    )

    assert expanded == ("alpha", "beta", "gamma", "delta", "epsilon")
    assert all(mapping.canonical_node_ids for mapping in mappings)


def test_compaction_rerun_returns_existing_manifest(tmp_path: Path) -> None:
    manifest_path = _write_tree_fixture(
        tmp_path,
        child_ids=("alpha", "beta"),
        child_summaries=frozenset({"alpha", "beta"}),
    )

    service = TreeCompactionService()
    request = TreeCompactionRequest(
        tree_manifest_path=str(manifest_path),
        compaction_run_id="rerun",
    )

    first = service.compact(request)
    second = service.compact(request)

    assert second == first
