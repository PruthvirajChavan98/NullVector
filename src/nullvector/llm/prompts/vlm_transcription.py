"""Prompt builder for VLM page-image-to-Markdown transcription."""

from __future__ import annotations

from nullvector.llm.types import LLMMessage, LLMRole


def build_vlm_transcription_messages(
    *,
    page_index: int,
    total_pages: int,
) -> tuple[LLMMessage, ...]:
    """Build prompt messages for VLM page transcription.

    The actual page image is supplied as a ``RegionImageInput`` attachment
    alongside the ``TextGatewayRequest``; this builder only constructs the
    text-based instruction messages.

    The VLM returns **raw Markdown text** — no JSON wrapper.  Table and image
    detection is handled heuristically by the caller.
    """

    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are a precise document transcription system. "
                "Convert the attached page image into clean, well-structured Markdown. "
                "Preserve all text content exactly as it appears. "
                "Render tables as Markdown tables with proper column alignment. "
                "Describe all figures, diagrams, and images in square brackets. "
                "Preserve heading hierarchy using Markdown heading levels (# ## ###). "
                "Before each heading, emit an HTML comment anchor in this exact format: "
                "<!-- SECTION_ANCHOR: level=N, title='Heading Text' --> "
                "where N is the heading level (1 for #, 2 for ##, etc.) and the title "
                "is the heading text using single quotes only (never double quotes). "
                "This anchor must appear on the line immediately before its heading. "
                "Do not add commentary or interpretation beyond what is on the page. "
                "Return ONLY the Markdown text — no JSON, no code fences, no wrapper."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(f"Transcribe this page to Markdown. Page {page_index + 1} of {total_pages}."),
        ),
    )


__all__ = [
    "build_vlm_transcription_messages",
]
