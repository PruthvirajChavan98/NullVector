"""Unit tests for the VLM transcription prompt builder."""

from __future__ import annotations

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
    assert "SECTION_ANCHOR" in system_content
    assert "no JSON" in system_content.lower() or "no json" in system_content.lower()


def test_build_vlm_transcription_messages_user_includes_page_info() -> None:
    messages = build_vlm_transcription_messages(page_index=3, total_pages=10)
    user_content = messages[1].content
    assert "Page 4 of 10" in user_content


def test_build_vlm_transcription_messages_no_json_instruction() -> None:
    """The user prompt must NOT ask for JSON — VLM returns raw Markdown."""
    messages = build_vlm_transcription_messages(page_index=0, total_pages=1)
    user_content = messages[1].content
    assert "JSON object" not in user_content
    assert "json" not in user_content.lower()
