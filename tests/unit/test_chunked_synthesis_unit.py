"""Unit tests for map-reduce chunked hierarchy synthesis (Phase 3)."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.gateway import (
    ChunkHierarchyResponse,
    HierarchySynthesisNode,
    MergeHierarchyResponse,
)
from nullvector.domain.ledger import OutlineEntry, OutlineSource
from nullvector.domain.tree import TreeSettings
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.llm.prompts.chunk_hierarchy import build_chunk_hierarchy_messages
from nullvector.llm.prompts.merge_hierarchy import build_merge_hierarchy_messages
from nullvector.llm.types import LLMRole
from nullvector.tree.chunked_synthesis import _compute_chunk_boundaries
from nullvector.tree.llm_hierarchy import LLMHierarchyBuilder

DOC_ID = "a" * 64


# --- Chunk boundary computation ---


def test_chunk_boundaries_small_document() -> None:
    bounds = _compute_chunk_boundaries(total_pages=5, chunk_size=10, chunk_overlap=2)
    assert bounds == ((0, 4),)


def test_chunk_boundaries_exact_chunk_size() -> None:
    bounds = _compute_chunk_boundaries(total_pages=10, chunk_size=10, chunk_overlap=2)
    assert bounds == ((0, 9),)


def test_chunk_boundaries_two_chunks_with_overlap() -> None:
    bounds = _compute_chunk_boundaries(total_pages=15, chunk_size=10, chunk_overlap=2)
    # step = 10 - 2 = 8, so chunks: [0..9], [8..14]
    assert len(bounds) == 2
    assert bounds[0] == (0, 9)
    assert bounds[1] == (8, 14)


def test_chunk_boundaries_three_chunks() -> None:
    bounds = _compute_chunk_boundaries(total_pages=25, chunk_size=10, chunk_overlap=2)
    # step=8: [0..9], [8..17], [16..24]
    assert len(bounds) == 3
    assert bounds[0] == (0, 9)
    assert bounds[1] == (8, 17)
    assert bounds[2] == (16, 24)


def test_chunk_boundaries_overlap_1() -> None:
    bounds = _compute_chunk_boundaries(total_pages=20, chunk_size=10, chunk_overlap=1)
    # step=9: [0..9], [9..18], [18..19]
    assert len(bounds) == 3
    assert bounds[2][1] == 19


def test_chunk_boundaries_zero_pages() -> None:
    bounds = _compute_chunk_boundaries(total_pages=0, chunk_size=10, chunk_overlap=2)
    assert bounds == ()


# --- Chunk hierarchy prompt ---


def test_chunk_prompt_includes_global_page_indices() -> None:
    pages = ("p0", "p1", "p2", "p3", "p4")
    messages = build_chunk_hierarchy_messages(
        markdown_pages=pages,
        chunk_start_page=2,
        chunk_end_page=4,
    )
    assert len(messages) == 2
    assert messages[0].role is LLMRole.SYSTEM
    assert "chunk" in messages[0].content.lower()
    user_content = messages[1].content
    assert "[Page 2]" in user_content
    assert "[Page 4]" in user_content
    assert "[Page 0]" not in user_content


def test_chunk_prompt_includes_outline_for_range() -> None:
    pages = ("p0", "p1", "p2", "p3", "p4")
    entries = (
        OutlineEntry(title="A", level=1, page_index=1, source=OutlineSource.PYMUPDF),
        OutlineEntry(title="B", level=1, page_index=3, source=OutlineSource.PYMUPDF),
    )
    messages = build_chunk_hierarchy_messages(
        markdown_pages=pages,
        chunk_start_page=2,
        chunk_end_page=4,
        outline_entries=entries,
    )
    user_content = messages[1].content
    assert "B" in user_content
    # "A" is on page 1 which is outside the chunk range [2..4]
    assert '"title": "A"' not in user_content


def test_chunk_prompt_includes_previous_section() -> None:
    pages = ("p0", "p1")
    messages = build_chunk_hierarchy_messages(
        markdown_pages=pages,
        chunk_start_page=0,
        chunk_end_page=1,
        previous_last_section="Chapter 3",
    )
    assert "Chapter 3" in messages[1].content


# --- Merge hierarchy prompt ---


def test_merge_prompt_includes_all_chunks() -> None:
    chunks = (
        ChunkHierarchyResponse(
            nodes=(HierarchySynthesisNode(title="Intro", level=1, start_page=0, end_page=4),),
        ),
        ChunkHierarchyResponse(
            nodes=(HierarchySynthesisNode(title="Methods", level=1, start_page=5, end_page=9),),
        ),
    )
    messages = build_merge_hierarchy_messages(chunk_responses=chunks, total_pages=10)
    assert len(messages) == 2
    assert "merge" in messages[0].content.lower()
    user_content = messages[1].content
    assert "Intro" in user_content
    assert "Methods" in user_content


# --- Domain models ---


def test_chunk_hierarchy_response_default_empty() -> None:
    resp = ChunkHierarchyResponse()
    assert resp.nodes == ()


def test_merge_hierarchy_response_default_empty() -> None:
    resp = MergeHierarchyResponse()
    assert resp.nodes == ()


def test_tree_settings_chunking_defaults() -> None:
    settings = TreeSettings()
    assert settings.hierarchy_chunk_size == 10
    assert settings.hierarchy_chunk_overlap == 2
    assert settings.hierarchy_chunking_threshold == 15


def test_tree_settings_chunking_custom() -> None:
    settings = TreeSettings(
        hierarchy_chunk_size=5,
        hierarchy_chunk_overlap=1,
        hierarchy_chunking_threshold=8,
    )
    assert settings.hierarchy_chunk_size == 5
    assert settings.hierarchy_chunk_overlap == 1
    assert settings.hierarchy_chunking_threshold == 8


# --- Integration with LLMHierarchyBuilder ---


def _make_gateway_for_chunked(tmp_path: Path) -> GatewayService:
    """Build a gateway that handles chunk, merge, and single-shot operations."""
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
                            {"title": "Root", "level": 1, "start_page": 0, "end_page": 2},
                        ],
                    },
                ),
                "chunk_hierarchy_synthesis": NoopScriptedResponse(
                    output_json={
                        "nodes": [
                            {"title": "Chunk Section", "level": 1, "start_page": 0, "end_page": 9},
                        ],
                    },
                ),
                "merge_hierarchy_synthesis": NoopScriptedResponse(
                    output_json={
                        "nodes": [
                            {"title": "Merged Root", "level": 1, "start_page": 0, "end_page": 19},
                        ],
                    },
                ),
            }
        ),
    )


def test_builder_uses_single_shot_below_threshold(tmp_path: Path) -> None:
    gateway = _make_gateway_for_chunked(tmp_path)
    builder = LLMHierarchyBuilder(gateway=gateway)
    settings = TreeSettings(hierarchy_chunking_threshold=15)

    # 3 pages < 15 threshold => single-shot
    nodes, _, _, report = builder.build(
        document_id=DOC_ID,
        tree_run_id="single-shot-test",
        markdown_pages=("p0", "p1", "p2"),
        settings=settings,
    )

    assert report.synthesis_method == "llm"
    assert nodes[0].title == "Root"


def test_builder_uses_map_reduce_above_threshold(tmp_path: Path) -> None:
    gateway = _make_gateway_for_chunked(tmp_path)
    builder = LLMHierarchyBuilder(gateway=gateway)
    settings = TreeSettings(hierarchy_chunking_threshold=5, hierarchy_chunk_size=5)

    # 20 pages >= 5 threshold => map-reduce
    pages = tuple(f"page {i}" for i in range(20))
    nodes, _, _, report = builder.build(
        document_id=DOC_ID,
        tree_run_id="map-reduce-test",
        markdown_pages=pages,
        settings=settings,
    )

    assert report.synthesis_method == "llm_map_reduce"
    assert nodes[0].title == "Merged Root"


def test_builder_without_gateway_ignores_settings() -> None:
    builder = LLMHierarchyBuilder(gateway=None)
    settings = TreeSettings(hierarchy_chunking_threshold=1)

    # Even with threshold=1, no gateway means fallback
    nodes, _, _, report = builder.build(
        document_id=DOC_ID,
        tree_run_id="no-gw-test",
        markdown_pages=("page 0",),
        settings=settings,
    )

    assert report.synthesis_method == "fallback_single_node"


def test_builder_default_settings_when_none(tmp_path: Path) -> None:
    gateway = _make_gateway_for_chunked(tmp_path)
    builder = LLMHierarchyBuilder(gateway=gateway)

    # No settings => default TreeSettings with threshold=15 => 3 pages = single-shot
    nodes, _, _, report = builder.build(
        document_id=DOC_ID,
        tree_run_id="default-test",
        markdown_pages=("p0", "p1", "p2"),
    )

    assert report.synthesis_method == "llm"
