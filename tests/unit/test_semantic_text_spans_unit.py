"""Unit coverage for semantic owned-span text extraction helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from nullvector.domain import (
    AnchorSource,
    ContentSpan,
    HierarchyNode,
    HierarchyOrigin,
    NodeAnchor,
    NodeOwnedSpan,
    PageSourceAnchor,
    PageSpan,
)
from nullvector.semantic._text_spans import bounded_fragments, text_for_node
from nullvector.tree.headings import PageArtifacts


def _node(*, owned_spans: tuple[NodeOwnedSpan, ...], end_page: int = 0) -> HierarchyNode:
    return HierarchyNode(
        node_id="node-1",
        document_id="d" * 64,
        path=("Section",),
        level=1,
        title="Section",
        normalized_title="section",
        page_span=PageSpan(start_page=0, end_page=end_page),
        heading_anchor=NodeAnchor(
            page=0,
            start_offset=0,
            end_offset=7,
            anchor_text="Section",
            anchor_source=AnchorSource.TEXT,
            occurrence_index=0,
        ),
        owned_spans=owned_spans,
        source_anchors=(
            PageSourceAnchor(
                page=0,
                start_offset=0,
                end_offset=7,
                quote="Section",
            ),
        ),
        origin=HierarchyOrigin.INFERRED,
        confidence=1.0,
    )


def test_text_for_node_prefers_owned_spans_over_full_page_text() -> None:
    node = _node(
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=0,
                    start_offset=8,
                    end_page=0,
                    end_offset=18,
                ),
            ),
        )
    )
    pages_by_index = {
        0: PageArtifacts(
            page_index=0,
            text="Section\nbody only\nsibling content",
            rawdict=None,
        )
    }

    assert text_for_node(node, cast(Mapping[int, Any], pages_by_index)) == "body only"


def test_text_for_node_falls_back_to_page_span_when_owned_spans_are_empty() -> None:
    node = _node(
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=0,
                    start_offset=0,
                    end_page=0,
                    end_offset=0,
                ),
            ),
        ),
        end_page=1,
    )
    pages_by_index = {
        0: PageArtifacts(page_index=0, text="Page zero text", rawdict=None),
        1: PageArtifacts(page_index=1, text="Page one text", rawdict=None),
    }

    assert (
        text_for_node(
            node,
            cast(Mapping[int, Any], pages_by_index),
        )
        == "Page zero text\nPage one text"
    )


def test_bounded_fragments_respects_total_character_budget() -> None:
    fragments = bounded_fragments(("alpha", "beta", "gamma"), max_chars=7)

    assert fragments == ("alpha", "be")
