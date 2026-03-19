"""Tree-search retrieval service and helper tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullvector._text import tokenize
from nullvector.domain.common import ContentSpan, NodeOwnedSpan, PageSourceAnchor, PageSpan
from nullvector.domain.ledger import AcquisitionRequest, SourceDocumentKind
from nullvector.domain.retrieval import (
    RetrievalCorpus,
    RetrievalEvidence,
    RetrievalModality,
    RetrievalUnitType,
    TreeSearchRequest,
    TreeSearchTerminationSignal,
)
from nullvector.domain.tree import (
    AnchorSource,
    HierarchyNode,
    HierarchyOrigin,
    NodeAnchor,
    NodeCard,
    NodeSummary,
    NodeSummaryMethod,
    TreeBuildRequest,
)
from nullvector.ingest.acquisition_service import AcquisitionService
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.retrieval import (
    QueryPlanner,
    RetrievalCorpusBuilder,
    RetrievalRanker,
    RetrievalService,
)
from nullvector.retrieval._artifacts import load_node_cards, load_tree_manifest
from nullvector.retrieval._tree_search_runtime import (
    build_adjacency_maps,
    build_frontier_node,
    contextual_retrieval_units,
    frontier_score,
    seed_frontier,
)
from nullvector.retrieval.tree_search import TreeSearchService
from nullvector.storage import FilesystemStorageConfig, build_document_store
from nullvector.tree import build_tree


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
        heading_anchor=NodeAnchor(
            page=start_page,
            start_offset=0,
            end_offset=len(title),
            anchor_text=title,
            anchor_source=AnchorSource.TEXT,
            occurrence_index=0,
        ),
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=start_page,
                    start_offset=0,
                    end_page=end_page,
                    end_offset=32,
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


def _node_card(
    *,
    node_id: str,
    title: str,
    path: tuple[str, ...],
    level: int,
    start_page: int,
    end_page: int,
    keywords: tuple[str, ...] = (),
) -> NodeCard:
    return NodeCard(
        node_id=node_id,
        document_id="a" * 64,
        path=path,
        level=level,
        title=title,
        page_span=PageSpan(start_page=start_page, end_page=end_page),
        owned_spans=(),
        source_anchors=(
            PageSourceAnchor(
                page=start_page,
                start_offset=0,
                end_offset=min(len(title), 16),
                quote=title[:16],
            ),
        ),
        keywords=keywords,
    )


def _node_summary(*, node_id: str, summary: str, keywords: tuple[str, ...] = ()) -> NodeSummary:
    return NodeSummary(
        node_id=node_id,
        summary=summary,
        keywords=keywords,
        summary_method=NodeSummaryMethod.PASSTHROUGH,
        token_count=8,
        estimated_token_count=8,
        exact_token_count=8,
        tokenizer_identity="synthetic",
    )


def _retrieval_unit(
    *,
    unit_id: str,
    unit_type: RetrievalUnitType,
    page_span: PageSpan,
    node_id: str | None = None,
    title: str | None = None,
    text: str | None = None,
) -> RetrievalEvidence:
    return RetrievalEvidence(
        unit_id=unit_id,
        document_id="a" * 64,
        unit_type=unit_type,
        modality=RetrievalModality.TEXT,
        page_span=page_span,
        node_id=node_id,
        title=title,
        text=text,
    )


def _build_markdown_tree_search_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    source_path = tmp_path / "tree-search.md"
    source_path.write_text(
        "\n".join(
            (
                "# Revenue Overview",
                "Alpha revenue growth accelerated this quarter.",
                "Margins improved across the business.",
                "",
                "# Litigation Summary",
                "Major case deadlines shifted into the next quarter.",
                "No settlement has been reached.",
            )
        ),
        encoding="utf-8",
    )

    acquisition_manifest = AcquisitionService().acquire(
        AcquisitionRequest(
            source_path=str(source_path),
            acquisition_run_id="tree-search-acquire",
            artifact_root=str(tmp_path / "acquisition"),
            source_kind=SourceDocumentKind.MARKDOWN,
            provider_identity="markdown_native",
        )
    )
    if acquisition_manifest.artifact_root is None:
        pytest.fail("expected acquisition artifact_root for tree-search fixture")
    acquisition_manifest_path = str(Path(acquisition_manifest.artifact_root) / "manifest.json")
    tree_manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=acquisition_manifest_path,
            tree_run_id="tree-search-tree",
            summarize=False,
        )
    )
    if tree_manifest.artifact_root is None:
        pytest.fail("expected tree artifact_root for tree-search fixture")
    retrieval_manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=acquisition_manifest_path,
        tree_manifest_path=str(Path(tree_manifest.artifact_root) / "manifest.json"),
    )
    if retrieval_manifest.artifact_root is None:
        pytest.fail("expected retrieval artifact_root for tree-search fixture")
    return (
        Path(tree_manifest.artifact_root) / "manifest.json",
        Path(retrieval_manifest.artifact_root) / "manifest.json",
    )


def test_build_adjacency_maps_orders_children_by_page_and_path() -> None:
    nodes = (
        _hierarchy_node(
            node_id="b",
            title="Beta",
            path=("Root", "Beta"),
            level=2,
            start_page=2,
            end_page=2,
            parent_id="root",
        ),
        _hierarchy_node(
            node_id="root",
            title="Root",
            path=("Root",),
            level=1,
            start_page=0,
            end_page=3,
        ),
        _hierarchy_node(
            node_id="a",
            title="Alpha",
            path=("Root", "Alpha"),
            level=2,
            start_page=1,
            end_page=1,
            parent_id="root",
        ),
    )
    node_cards_by_id = {
        "root": _node_card(
            node_id="root",
            title="Root",
            path=("Root",),
            level=1,
            start_page=0,
            end_page=3,
        ),
        "a": _node_card(
            node_id="a",
            title="Alpha",
            path=("Root", "Alpha"),
            level=2,
            start_page=1,
            end_page=1,
        ),
        "b": _node_card(
            node_id="b",
            title="Beta",
            path=("Root", "Beta"),
            level=2,
            start_page=2,
            end_page=2,
        ),
    }

    children_by_parent, ordered = build_adjacency_maps(nodes, node_cards_by_id=node_cards_by_id)

    assert ordered == ("root", "a", "b")
    assert children_by_parent[None] == ("root",)
    assert children_by_parent["root"] == ("a", "b")


def test_seed_frontier_uses_explicit_roots() -> None:
    nodes = (
        _hierarchy_node(
            node_id="root-a",
            title="Revenue Overview",
            path=("Revenue Overview",),
            level=1,
            start_page=0,
            end_page=0,
        ),
        _hierarchy_node(
            node_id="root-b",
            title="Litigation Summary",
            path=("Litigation Summary",),
            level=1,
            start_page=1,
            end_page=1,
        ),
    )
    node_cards_by_id = {
        "root-a": _node_card(
            node_id="root-a",
            title="Revenue Overview",
            path=("Revenue Overview",),
            level=1,
            start_page=0,
            end_page=0,
        ),
        "root-b": _node_card(
            node_id="root-b",
            title="Litigation Summary",
            path=("Litigation Summary",),
            level=1,
            start_page=1,
            end_page=1,
        ),
    }

    assert seed_frontier(committed_nodes=nodes, node_cards_by_id=node_cards_by_id) == (
        "root-a",
        "root-b",
    )


def test_frontier_score_uses_title_summary_and_keywords() -> None:
    planner = QueryPlanner()
    plan = planner.plan("alpha revenue growth")
    score_with_summary = frontier_score(
        build_frontier_node(
            "revenue",
            nodes_by_id={
                "revenue": _hierarchy_node(
                    node_id="revenue",
                    title="Revenue Overview",
                    path=("Revenue Overview",),
                    level=1,
                    start_page=0,
                    end_page=0,
                )
            },
            node_cards_by_id={
                "revenue": _node_card(
                    node_id="revenue",
                    title="Revenue Overview",
                    path=("Revenue Overview",),
                    level=1,
                    start_page=0,
                    end_page=0,
                    keywords=("alpha", "revenue"),
                )
            },
            node_summaries_by_id={
                "revenue": _node_summary(
                    node_id="revenue",
                    summary="Alpha revenue growth accelerated.",
                    keywords=("revenue", "growth"),
                )
            },
        ),
        plan=plan,
        query_tokens=tuple(tokenize("alpha revenue growth")),
    )
    score_without_summary = frontier_score(
        build_frontier_node(
            "revenue",
            nodes_by_id={
                "revenue": _hierarchy_node(
                    node_id="revenue",
                    title="Revenue Overview",
                    path=("Revenue Overview",),
                    level=1,
                    start_page=0,
                    end_page=0,
                )
            },
            node_cards_by_id={
                "revenue": _node_card(
                    node_id="revenue",
                    title="Revenue Overview",
                    path=("Revenue Overview",),
                    level=1,
                    start_page=0,
                    end_page=0,
                    keywords=("alpha",),
                )
            },
            node_summaries_by_id={},
        ),
        plan=plan,
        query_tokens=tuple(tokenize("alpha revenue growth")),
    )

    assert score_with_summary > score_without_summary


def test_contextual_retrieval_units_include_only_intersecting_spans() -> None:
    corpus = RetrievalCorpus(
        document_id="a" * 64,
        units=(
            _retrieval_unit(
                unit_id="page-0",
                unit_type=RetrievalUnitType.PAGE_TEXT,
                page_span=PageSpan(start_page=0, end_page=0),
            ),
            _retrieval_unit(
                unit_id="page-2",
                unit_type=RetrievalUnitType.PAGE_TEXT,
                page_span=PageSpan(start_page=2, end_page=2),
            ),
            _retrieval_unit(
                unit_id="node-1",
                unit_type=RetrievalUnitType.NODE_TEXT,
                page_span=PageSpan(start_page=0, end_page=0),
                node_id="node-1",
            ),
        ),
    )

    contextual = contextual_retrieval_units(
        corpus,
        selected_page_spans=(PageSpan(start_page=0, end_page=1),),
    )

    assert tuple(unit.unit_id for unit in contextual) == ("page-0",)


def test_tree_search_selects_relevant_nodes_and_returns_narrowed_hits(tmp_path: Path) -> None:
    tree_manifest_path, retrieval_manifest_path = _build_markdown_tree_search_artifacts(tmp_path)
    planner = QueryPlanner()
    retrieval_service = RetrievalService(planner, RetrievalRanker())
    service = TreeSearchService(
        planner,
        retrieval_service,
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts")),
    )

    response = service.search(
        TreeSearchRequest(
            query="alpha revenue growth",
            tree_manifest_path=str(tree_manifest_path),
            retrieval_manifest_path=str(retrieval_manifest_path),
            search_run_id="tree-search-001",
        )
    )

    assert response.selected_nodes
    assert response.selected_nodes[0].retrieval_evidence_ids
    assert any(
        hit.unit.node_id == response.selected_nodes[0].node_id for hit in response.retrieval_hits
    )
    assert Path(response.trace_path).exists()
    assert Path(response.results_path).exists()


def test_tree_search_gateway_assisted_frontier_selection(tmp_path: Path) -> None:
    tree_manifest_path, retrieval_manifest_path = _build_markdown_tree_search_artifacts(tmp_path)
    store = build_document_store(None, default_filesystem_root=".")
    tree_manifest = load_tree_manifest(store, str(tree_manifest_path))
    assert tree_manifest is not None
    node_cards = load_node_cards(store, tree_manifest)
    revenue_node = next(node_card for node_card in node_cards if "Revenue" in node_card.title)

    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "tree_search_frontier": NoopScriptedResponse(
                    output_json={
                        "selected_node_ids": [revenue_node.node_id],
                        "selection_reason": "Revenue branch is most relevant.",
                        "termination_signal": "evidence_sufficient",
                    }
                )
            }
        ),
    )
    planner = QueryPlanner()
    retrieval_service = RetrievalService(planner, RetrievalRanker())
    service = TreeSearchService(
        planner,
        retrieval_service,
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts")),
    )

    response = service.search(
        TreeSearchRequest(
            query="alpha revenue growth",
            tree_manifest_path=str(tree_manifest_path),
            retrieval_manifest_path=str(retrieval_manifest_path),
            search_run_id="tree-search-002",
        ),
        gateway=gateway,
    )

    assert response.search_mode is not None
    assert response.search_mode.value == "llm"
    assert response.trace[0].selected_node_ids == (revenue_node.node_id,)
    assert response.selected_nodes[0].node_id == revenue_node.node_id


def test_tree_search_gateway_rejects_invalid_frontier_node_ids(tmp_path: Path) -> None:
    tree_manifest_path, retrieval_manifest_path = _build_markdown_tree_search_artifacts(tmp_path)
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "tree_search_frontier": NoopScriptedResponse(
                    output_json={
                        "selected_node_ids": ["not-a-real-node"],
                        "selection_reason": "Invalid selection.",
                        "termination_signal": None,
                    }
                )
            }
        ),
    )
    planner = QueryPlanner()
    retrieval_service = RetrievalService(planner, RetrievalRanker())
    service = TreeSearchService(
        planner,
        retrieval_service,
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts")),
    )

    with pytest.raises(ValueError, match="outside the provided frontier"):
        service.search(
            TreeSearchRequest(
                query="alpha revenue growth",
                tree_manifest_path=str(tree_manifest_path),
                retrieval_manifest_path=str(retrieval_manifest_path),
                search_run_id="tree-search-003",
            ),
            gateway=gateway,
        )


def test_tree_search_falls_back_to_flat_retrieval_when_first_frontier_is_not_positive(
    tmp_path: Path,
) -> None:
    tree_manifest_path, retrieval_manifest_path = _build_markdown_tree_search_artifacts(tmp_path)
    planner = QueryPlanner()
    retrieval_service = RetrievalService(planner, RetrievalRanker())
    service = TreeSearchService(
        planner,
        retrieval_service,
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts")),
    )

    response = service.search(
        TreeSearchRequest(
            query="zebra invoice compliance",
            tree_manifest_path=str(tree_manifest_path),
            retrieval_manifest_path=str(retrieval_manifest_path),
            search_run_id="tree-search-004",
        )
    )

    assert (
        response.trace[0].termination_signal
        is TreeSearchTerminationSignal.FALLBACK_TO_FLAT_RETRIEVAL
    )
    assert response.selected_nodes == ()
    assert response.retrieval_hits
    results_payload = json.loads(Path(response.results_path).read_text(encoding="utf-8"))
    assert results_payload["retrieval_hits"]
