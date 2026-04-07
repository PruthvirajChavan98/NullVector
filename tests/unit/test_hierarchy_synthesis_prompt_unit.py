"""Unit tests for the hierarchy synthesis prompt builder and response models."""

from __future__ import annotations

import pytest

from nullvector.domain.gateway import HierarchySynthesisNode, HierarchySynthesisResponse
from nullvector.domain.ledger import OutlineEntry, OutlineSource
from nullvector.llm.prompts.hierarchy_synthesis import build_hierarchy_synthesis_messages
from nullvector.llm.types import LLMRole


def test_build_messages_returns_system_and_user() -> None:
    messages = build_hierarchy_synthesis_messages(
        markdown_pages=("# Title\nBody text.",),
    )
    assert len(messages) == 2
    assert messages[0].role is LLMRole.SYSTEM
    assert messages[1].role is LLMRole.USER


def test_system_prompt_mentions_hierarchy() -> None:
    messages = build_hierarchy_synthesis_messages(markdown_pages=("text",))
    assert "hierarchical" in messages[0].content.lower()


def test_user_prompt_includes_page_count() -> None:
    messages = build_hierarchy_synthesis_messages(
        markdown_pages=("page 0", "page 1", "page 2"),
    )
    assert "page_count" in messages[1].content
    assert "3" in messages[1].content


def test_user_prompt_includes_outline_entries() -> None:
    entries = (
        OutlineEntry(title="Intro", level=1, page_index=0, source=OutlineSource.PYMUPDF),
    )
    messages = build_hierarchy_synthesis_messages(
        markdown_pages=("page",),
        outline_entries=entries,
    )
    assert "Intro" in messages[1].content


def test_user_prompt_includes_page_text() -> None:
    messages = build_hierarchy_synthesis_messages(
        markdown_pages=("# Hello World\nThis is content.",),
    )
    assert "Hello World" in messages[1].content


def test_long_page_text_is_previewed() -> None:
    long_text = "x" * 1000
    messages = build_hierarchy_synthesis_messages(
        markdown_pages=(long_text,),
    )
    # Preview should be 500 chars, not full 1000
    user_content = messages[1].content
    assert "length" in user_content
    assert "1000" in user_content


def test_hierarchy_synthesis_node_accepts_valid_input() -> None:
    node = HierarchySynthesisNode(
        title="Introduction",
        level=1,
        start_page=0,
        end_page=2,
        summary_hint="Overview section",
    )
    assert node.title == "Introduction"
    assert node.level == 1
    assert node.summary_hint == "Overview section"


def test_hierarchy_synthesis_node_defaults() -> None:
    node = HierarchySynthesisNode(
        title="Section",
        level=1,
        start_page=0,
        end_page=0,
    )
    assert node.summary_hint is None


def test_hierarchy_synthesis_node_rejects_empty_title() -> None:
    with pytest.raises(ValueError):
        HierarchySynthesisNode(title="", level=1, start_page=0, end_page=0)


def test_hierarchy_synthesis_node_rejects_zero_level() -> None:
    with pytest.raises(ValueError):
        HierarchySynthesisNode(title="Section", level=0, start_page=0, end_page=0)


def test_hierarchy_synthesis_response_accepts_valid_nodes() -> None:
    response = HierarchySynthesisResponse(
        nodes=(
            HierarchySynthesisNode(title="Root", level=1, start_page=0, end_page=1),
            HierarchySynthesisNode(title="Child", level=2, start_page=0, end_page=0),
        )
    )
    assert len(response.nodes) == 2


def test_hierarchy_synthesis_response_empty_nodes() -> None:
    response = HierarchySynthesisResponse(nodes=())
    assert len(response.nodes) == 0


def test_hierarchy_synthesis_response_default_empty() -> None:
    response = HierarchySynthesisResponse()
    assert response.nodes == ()
