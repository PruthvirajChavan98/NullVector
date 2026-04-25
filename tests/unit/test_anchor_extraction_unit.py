"""Unit tests for semantic anchor extraction (Phase 2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nullvector.domain.ledger import SectionAnchorRecord
from nullvector.ingest.vlm_transcriber import (
    PageTranscription,
    SectionAnchor,
    extract_section_anchors,
)


def test_extract_single_anchor() -> None:
    text = '<!-- SECTION_ANCHOR: level=1, title="Introduction" -->\n# Introduction\n\nBody text.'
    anchors = extract_section_anchors(text, page_index=0)

    assert len(anchors) == 1
    assert anchors[0].page_index == 0
    assert anchors[0].level == 1
    assert anchors[0].title == "Introduction"
    assert anchors[0].char_offset == 0


def test_extract_multiple_anchors() -> None:
    text = (
        '<!-- SECTION_ANCHOR: level=1, title="Chapter 1" -->\n# Chapter 1\n\n'
        '<!-- SECTION_ANCHOR: level=2, title="Section 1.1" -->\n## Section 1.1\n'
    )
    anchors = extract_section_anchors(text, page_index=3)

    assert len(anchors) == 2
    assert anchors[0].title == "Chapter 1"
    assert anchors[0].level == 1
    assert anchors[1].title == "Section 1.1"
    assert anchors[1].level == 2
    assert all(a.page_index == 3 for a in anchors)


def test_extract_no_anchors_from_plain_markdown() -> None:
    text = "# Introduction\n\nJust plain Markdown with no anchor comments."
    anchors = extract_section_anchors(text, page_index=0)
    assert anchors == ()


def test_extract_skips_malformed_anchors() -> None:
    text = (
        '<!-- SECTION_ANCHOR: level=abc, title="Bad" -->\n'
        '<!-- SECTION_ANCHOR: level=2, title="Good" -->\n'
    )
    anchors = extract_section_anchors(text, page_index=0)
    # First one has non-numeric level — regex won't match "abc"
    # Actually regex \d+ won't match "abc" so it's skipped
    assert len(anchors) == 1
    assert anchors[0].title == "Good"


def test_extract_handles_extra_whitespace() -> None:
    text = '<!--  SECTION_ANCHOR:  level = 3 ,  title = "Spaced Out"  -->'
    anchors = extract_section_anchors(text, page_index=0)
    assert len(anchors) == 1
    assert anchors[0].title == "Spaced Out"
    assert anchors[0].level == 3


def test_extract_empty_string() -> None:
    anchors = extract_section_anchors("", page_index=0)
    assert anchors == ()


def test_char_offset_is_correct() -> None:
    prefix = "Some text before.\n"
    anchor = '<!-- SECTION_ANCHOR: level=1, title="Title" -->'
    text = prefix + anchor
    anchors = extract_section_anchors(text, page_index=0)
    assert len(anchors) == 1
    assert anchors[0].char_offset == len(prefix)


def test_section_anchor_model_frozen() -> None:
    anchor = SectionAnchor(page_index=0, level=1, title="Test", char_offset=0)
    with pytest.raises(ValidationError):
        anchor.level = 2


def test_page_transcription_includes_section_anchors() -> None:
    t = PageTranscription(
        page_index=0,
        markdown_text="# Test",
        section_anchors=(SectionAnchor(page_index=0, level=1, title="Test", char_offset=0),),
    )
    assert len(t.section_anchors) == 1


def test_page_transcription_default_empty_anchors() -> None:
    t = PageTranscription(page_index=0, markdown_text="# Test")
    assert t.section_anchors == ()


def test_section_anchor_record_model_validates() -> None:
    record = SectionAnchorRecord(page_index=0, level=1, title="Intro", char_offset=42)
    assert record.page_index == 0
    assert record.level == 1
    assert record.title == "Intro"
    assert record.char_offset == 42
