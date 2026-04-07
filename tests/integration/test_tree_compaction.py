"""Integration coverage for serving-tree compaction."""

from __future__ import annotations

from pathlib import Path

import pytest

from nullvector.domain.ledger import AcquisitionRequest, SourceDocumentKind
from nullvector.domain.retrieval import RetrievalUnitType
from nullvector.domain.tree import TreeBuildRequest, TreeCompactionRequest, TreeCompactionSettings
from nullvector.ingest.acquisition_service import AcquisitionService
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.retrieval import RetrievalCorpusBuilder, load_retrieval_corpus
from nullvector.tree import (
    TreeCompactionService,
    build_tree,
    expand_serving_node_ids_to_canonical_node_ids,
    load_compacted_node_mappings,
    load_compacted_tree,
    load_compacted_tree_manifest,
)


def _summary_gateway(tmp_path: Path) -> GatewayService:
    return GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "hierarchy_synthesis": NoopScriptedResponse(
                    output_json={
                        "nodes": [
                            {
                                "title": "Operating Handbook",
                                "level": 1,
                                "start_page": 0,
                                "end_page": 0,
                            },
                            {
                                "title": "Alpha Policies",
                                "level": 2,
                                "start_page": 0,
                                "end_page": 0,
                            },
                            {
                                "title": "Beta Policies",
                                "level": 2,
                                "start_page": 0,
                                "end_page": 0,
                            },
                            {
                                "title": "Gamma Policies",
                                "level": 2,
                                "start_page": 0,
                                "end_page": 0,
                            },
                            {
                                "title": "Delta Policies",
                                "level": 2,
                                "start_page": 0,
                                "end_page": 0,
                            },
                            {
                                "title": "Epsilon Policies",
                                "level": 2,
                                "start_page": 0,
                                "end_page": 0,
                            },
                        ]
                    }
                ),
                "summarize_leaf_node": NoopScriptedResponse(
                    output_json={"summary": "leaf summary", "keywords": ["leaf"]}
                ),
                "summarize_parent_node": NoopScriptedResponse(
                    output_json={"summary": "parent summary", "keywords": ["parent"]}
                ),
            }
        ),
    )


@pytest.mark.skip(reason="summarization not wired in new tree pipeline (Phase 3 scope)")
def test_tree_compaction_persists_artifacts_and_maps_back_to_retrieval_evidence(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "serving-tree.md"
    source_path.write_text(
        "\n".join(
            (
                "# Operating Handbook",
                "Root overview for the handbook.",
                "",
                "## Alpha Policies",
                "Alpha policy details and revenue guidance.",
                "",
                "## Beta Policies",
                "Beta policy details and litigation guidance.",
                "",
                "## Gamma Policies",
                "Gamma policy details and deadlines.",
                "",
                "## Delta Policies",
                "Delta policy details and controls.",
                "",
                "## Epsilon Policies",
                "Epsilon policy details and escalations.",
            )
        ),
        encoding="utf-8",
    )

    acquisition_manifest = AcquisitionService().acquire(
        AcquisitionRequest(
            source_path=str(source_path),
            acquisition_run_id="compaction-acquire",
            artifact_root=str(tmp_path / "acquisition"),
            source_kind=SourceDocumentKind.MARKDOWN,
            provider_identity="markdown_native",
        )
    )
    assert acquisition_manifest.artifact_root is not None
    acquisition_manifest_path = str(Path(acquisition_manifest.artifact_root) / "manifest.json")
    gateway = _summary_gateway(tmp_path)
    tree_manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=acquisition_manifest_path,
            tree_run_id="compaction-tree",
            summarize=True,
        ),
        gateway=gateway,
    )
    assert tree_manifest.artifact_root is not None
    assert tree_manifest.committed_hierarchy_path is not None
    tree_manifest_path = Path(tree_manifest.artifact_root) / "manifest.json"
    committed_before = Path(tree_manifest.committed_hierarchy_path).read_text(encoding="utf-8")

    compaction_manifest = TreeCompactionService().compact(
        TreeCompactionRequest(
            tree_manifest_path=str(tree_manifest_path),
            compaction_run_id="serving-tree",
            settings=TreeCompactionSettings(max_children_per_node=2),
        )
    )
    retrieval_manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=acquisition_manifest_path,
        tree_manifest_path=str(tree_manifest_path),
    )

    assert compaction_manifest.artifact_root is not None
    manifest_path = Path(compaction_manifest.artifact_root) / "manifest.json"
    loaded_manifest = load_compacted_tree_manifest(manifest_path)
    compacted_tree = load_compacted_tree(compaction_manifest.compacted_tree_path)
    mappings = load_compacted_node_mappings(compaction_manifest.node_mapping_path)
    retrieval_corpus = load_retrieval_corpus(retrieval_manifest.corpus_path)

    root_node = next(node for node in compacted_tree if node.level == 1)
    merged_node = next(
        node
        for node in compacted_tree
        if node.serving_node_id.startswith(f"{root_node.serving_node_id}::compact::")
    )
    canonical_node_ids = expand_serving_node_ids_to_canonical_node_ids(
        (merged_node.serving_node_id,),
        mappings,
    )
    direct_evidence = tuple(
        unit
        for unit in retrieval_corpus.units
        if unit.node_id in canonical_node_ids
        and unit.unit_type in (RetrievalUnitType.NODE_TEXT, RetrievalUnitType.NODE_SUMMARY)
    )

    assert manifest_path.exists()
    assert Path(compaction_manifest.compacted_tree_path).exists()
    assert Path(compaction_manifest.node_mapping_path).exists()
    assert loaded_manifest == compaction_manifest
    assert len(root_node.child_serving_node_ids) <= 2
    assert canonical_node_ids
    assert direct_evidence
    assert (
        Path(tree_manifest.committed_hierarchy_path).read_text(encoding="utf-8") == committed_before
    )
