"""Unit tests for the LLM hierarchy builder."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.gateway import HierarchySynthesisNode, HierarchySynthesisResponse
from nullvector.domain.ledger import OutlineEntry, OutlineSource
from nullvector.domain.tree import HierarchyOrigin
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.tree.llm_hierarchy import LLMHierarchyBuilder, _build_nodes_from_response


def _make_gateway(tmp_path: Path, nodes: list[dict[str, object]]) -> GatewayService:
    return GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "hierarchy_synthesis": NoopScriptedResponse(
                    output_json={"nodes": nodes},
                ),
            }
        ),
    )


DOC_ID = "a" * 64


def test_build_with_gateway_returns_llm_nodes(tmp_path: Path) -> None:
    gateway = _make_gateway(
        tmp_path,
        [
            {"title": "Introduction", "level": 1, "start_page": 0, "end_page": 0},
            {"title": "Methods", "level": 1, "start_page": 1, "end_page": 2},
        ],
    )
    builder = LLMHierarchyBuilder(gateway=gateway)
    nodes, cards, spans, report = builder.build(
        document_id=DOC_ID,
        tree_run_id="test-run",
        markdown_pages=("# Intro", "# Methods", "Details"),
    )

    assert len(nodes) == 2
    assert nodes[0].title == "Introduction"
    assert nodes[1].title == "Methods"
    assert all(n.origin is HierarchyOrigin.LLM_SYNTHESIZED for n in nodes)
    assert report.synthesis_method == "llm"
    assert len(cards) == 2


def test_build_with_gateway_assigns_parent_ids(tmp_path: Path) -> None:
    gateway = _make_gateway(
        tmp_path,
        [
            {"title": "Root", "level": 1, "start_page": 0, "end_page": 1},
            {"title": "Child", "level": 2, "start_page": 0, "end_page": 0},
        ],
    )
    builder = LLMHierarchyBuilder(gateway=gateway)
    nodes, _, _, _ = builder.build(
        document_id=DOC_ID,
        tree_run_id="parent-test",
        markdown_pages=("root text", "child text"),
    )

    assert nodes[0].parent_id is None
    assert nodes[1].parent_id == nodes[0].node_id


def test_build_without_gateway_uses_outline_fallback() -> None:
    builder = LLMHierarchyBuilder(gateway=None)
    entries = (
        OutlineEntry(title="Chapter 1", level=1, page_index=0, source=OutlineSource.PYMUPDF),
        OutlineEntry(title="Chapter 2", level=1, page_index=1, source=OutlineSource.PYMUPDF),
    )
    nodes, cards, spans, report = builder.build(
        document_id=DOC_ID,
        tree_run_id="outline-fallback",
        markdown_pages=("page 0", "page 1"),
        outline_entries=entries,
    )

    assert len(nodes) == 2
    assert nodes[0].title == "Chapter 1"
    assert nodes[1].title == "Chapter 2"
    assert all(n.origin is HierarchyOrigin.OUTLINE for n in nodes)
    assert report.synthesis_method == "outline_fallback"


def test_build_without_gateway_or_outline_produces_single_root() -> None:
    builder = LLMHierarchyBuilder(gateway=None)
    nodes, cards, spans, report = builder.build(
        document_id=DOC_ID,
        tree_run_id="single-root",
        markdown_pages=("only page",),
    )

    assert len(nodes) == 1
    assert nodes[0].title == "Document Root"
    assert nodes[0].origin is HierarchyOrigin.INFERRED
    assert report.synthesis_method == "fallback_single_node"


def test_node_ids_are_stable_across_repeated_builds() -> None:
    builder = LLMHierarchyBuilder(gateway=None)
    entries = (
        OutlineEntry(title="Section A", level=1, page_index=0, source=OutlineSource.MARKDOWN),
    )
    nodes_1, _, _, _ = builder.build(
        document_id=DOC_ID,
        tree_run_id="run-1",
        markdown_pages=("page",),
        outline_entries=entries,
    )
    nodes_2, _, _, _ = builder.build(
        document_id=DOC_ID,
        tree_run_id="run-2",
        markdown_pages=("page",),
        outline_entries=entries,
    )

    assert nodes_1[0].node_id == nodes_2[0].node_id


def test_unassigned_spans_reported_for_gaps() -> None:
    builder = LLMHierarchyBuilder(gateway=None)
    entries = (OutlineEntry(title="Middle", level=1, page_index=1, source=OutlineSource.PYMUPDF),)
    nodes, _, spans, report = builder.build(
        document_id=DOC_ID,
        tree_run_id="gap-test",
        markdown_pages=("page 0", "page 1", "page 2"),
        outline_entries=entries,
    )

    assert report.unassigned_span_count >= 1
    assert any(s.reason == "before_first_heading" for s in spans)


def test_build_nodes_from_response_clamps_page_indices() -> None:
    response = HierarchySynthesisResponse(
        nodes=(HierarchySynthesisNode(title="Overflow", level=1, start_page=99, end_page=99),)
    )
    nodes = _build_nodes_from_response(response, document_id=DOC_ID, page_count=3)

    assert nodes[0].page_span.start_page == 2
    assert nodes[0].page_span.end_page == 2


def test_report_has_correct_counts() -> None:
    builder = LLMHierarchyBuilder(gateway=None)
    entries = (
        OutlineEntry(title="A", level=1, page_index=0, source=OutlineSource.PYMUPDF),
        OutlineEntry(title="B", level=1, page_index=2, source=OutlineSource.PYMUPDF),
    )
    _, _, spans, report = builder.build(
        document_id=DOC_ID,
        tree_run_id="count-test",
        markdown_pages=("p0", "p1", "p2", "p3"),
        outline_entries=entries,
    )

    assert report.committed_node_count == 2
    assert report.unassigned_span_count == len(spans)
    assert report.document_id == DOC_ID
    assert report.tree_run_id == "count-test"
