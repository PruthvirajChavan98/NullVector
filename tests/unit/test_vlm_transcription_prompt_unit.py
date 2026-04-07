"""Unit tests for the VLM transcription prompt builder and response model."""

from __future__ import annotations

import pytest

from nullvector.domain.gateway import VLMTranscriptionResponse
from nullvector.llm.prompts.vlm_transcription import build_vlm_transcription_messages
from nullvector.llm.types import LLMRole


def test_build_vlm_transcription_messages_returns_system_and_user() -> None:
    messages = build_vlm_transcription_messages(page_index=0, total_pages=5)
    assert len(messages) == 2
    assert messages[0].role is LLMRole.SYSTEM
    assert messages[1].role is LLMRole.USER


def test_build_vlm_transcription_messages_system_prompt_content() -> None:
    messages = build_vlm_transcription_messages(page_index=0, total_pages=1)
    system_content = messages[0].content
    assert "Markdown" in system_content
    assert "tables" in system_content.lower()


def test_build_vlm_transcription_messages_user_includes_page_metadata() -> None:
    messages = build_vlm_transcription_messages(page_index=3, total_pages=10)
    user_content = messages[1].content
    assert "page_index" in user_content
    assert "3" in user_content
    assert "total_pages" in user_content
    assert "10" in user_content


def test_vlm_transcription_response_accepts_valid_input() -> None:
    response = VLMTranscriptionResponse(
        markdown_text="# Title\n\nParagraph text.",
        has_tables=True,
        has_images=False,
    )
    assert response.markdown_text == "# Title\n\nParagraph text."
    assert response.has_tables is True
    assert response.has_images is False


def test_vlm_transcription_response_defaults() -> None:
    response = VLMTranscriptionResponse(markdown_text="content")
    assert response.has_tables is False
    assert response.has_images is False


def test_vlm_transcription_response_rejects_empty_markdown() -> None:
    with pytest.raises(ValueError):
        VLMTranscriptionResponse(markdown_text="")


def test_vlm_transcription_response_rejects_whitespace_only_markdown() -> None:
    with pytest.raises(ValueError):
        VLMTranscriptionResponse(markdown_text="   ")
