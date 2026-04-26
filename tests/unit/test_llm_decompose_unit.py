"""Unit tests for LLM-driven node decomposition."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.common import PageSpan
from nullvector.domain.tree import (
    DecompositionMethod,
    HierarchyNode,
    HierarchyOrigin,
    TreeSettings,
)
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.semantic.decompose import NodeDecomposer
from nullvector.tree.hierarchy import generate_node_id
from nullvector.tree.page_data import PageData

DOC_ID = "a" * 64


def _node(title: str, start_page: int, end_page: int, *, level: int = 1) -> HierarchyNode:
    path = (title,)
    return HierarchyNode(
        node_id=generate_node_id(DOC_ID, path, level, start_page, 0, 1, start_page),
        document_id=DOC_ID,
        path=path,
        level=level,
        title=title,
        normalized_title=title.casefold(),
        page_span=PageSpan(start_page=start_page, end_page=end_page),
        origin=HierarchyOrigin.LLM_SYNTHESIZED,
        confidence=0.8,
    )


def _pages(count: int) -> tuple[PageData, ...]:
    return tuple(PageData(page_index=i, text=f"Page {i} content.") for i in range(count))


def test_no_decomposition_when_within_page_limit() -> None:
    settings = TreeSettings(max_pages_per_leaf_node=10)
    decomposer = NodeDecomposer(settings)
    nodes = (_node("Small", 0, 2),)
    result_nodes, report = decomposer.decompose(nodes=nodes, pages=_pages(3), tree_run_id="test")

    assert len(result_nodes) == 1
    assert report.decomposition_method is DecompositionMethod.NONE
    assert report.new_child_count == 0


def test_no_decomposition_without_gateway_even_if_over_limit() -> None:
    settings = TreeSettings(max_pages_per_leaf_node=2)
    decomposer = NodeDecomposer(settings, gateway=None)
    nodes = (_node("Large", 0, 5),)
    result_nodes, report = decomposer.decompose(nodes=nodes, pages=_pages(6), tree_run_id="test")

    assert len(result_nodes) == 1
    assert report.decomposition_method is DecompositionMethod.NONE


def test_llm_decomposition_splits_large_node(tmp_path: Path) -> None:
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "decompose_large_node": NoopScriptedResponse(
                    output_json={
                        "entries": [
                            {"title": "Part A", "page_index": 0},
                            {"title": "Part B", "page_index": 3},
                        ]
                    }
                ),
            }
        ),
    )
    settings = TreeSettings(max_pages_per_leaf_node=2, max_decomposition_depth=1)
    decomposer = NodeDecomposer(settings, gateway=gateway)
    nodes = (_node("Large", 0, 5),)
    result_nodes, report = decomposer.decompose(nodes=nodes, pages=_pages(6), tree_run_id="test")

    assert report.decomposition_method is DecompositionMethod.LLM_ASSISTED
    assert report.new_child_count >= 2
    child_titles = {n.title for n in result_nodes if n.title != "Large"}
    assert "Part A" in child_titles
    assert "Part B" in child_titles


def test_decomposition_report_has_no_tokenizer_identity() -> None:
    settings = TreeSettings(max_pages_per_leaf_node=10)
    decomposer = NodeDecomposer(settings)
    _, report = decomposer.decompose(
        nodes=(_node("Small", 0, 0),), pages=_pages(1), tree_run_id="test"
    )

    assert report.tokenizer_identity is None


def test_page_count_threshold_is_inclusive() -> None:
    settings = TreeSettings(max_pages_per_leaf_node=3)
    decomposer = NodeDecomposer(settings, gateway=None)

    exactly_at_limit = (_node("Exact", 0, 2),)
    result, report = decomposer.decompose(
        nodes=exactly_at_limit, pages=_pages(3), tree_run_id="test"
    )
    assert report.decomposition_method is DecompositionMethod.NONE

    over_limit = (_node("Over", 0, 3),)
    result, report = decomposer.decompose(nodes=over_limit, pages=_pages(4), tree_run_id="test")
    assert report.decomposition_method is DecompositionMethod.NONE  # no gateway
