"""Prompt builder for VLM page-image-to-Markdown transcription."""

from __future__ import annotations

import json

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.llm.types import LLMMessage, LLMRole


class VLMTranscriptionResponse(NullVectorModel):
    """Typed structured response for VLM page transcription."""

    markdown_text: NonEmptyStr
    has_tables: bool = False
    has_images: bool = False


def build_vlm_transcription_messages(
    *,
    page_index: int,
    total_pages: int,
) -> tuple[LLMMessage, ...]:
    """Build prompt messages for VLM page transcription.

    The actual page image is supplied as a ``RegionImageInput`` attachment
    alongside the ``GatewayRequest``; this builder only constructs the
    text-based instruction messages.
    """

    payload = json.dumps(
        {"page_index": page_index, "total_pages": total_pages},
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
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
                "Do not add commentary or interpretation beyond what is on the page."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                f"Transcribe this page to Markdown.\n{payload}\n\n"
                "Return the transcription as a JSON object with fields: "
                "markdown_text (the full Markdown text), "
                "has_tables (boolean), "
                "has_images (boolean)."
            ),
        ),
    )


__all__ = [
    "VLMTranscriptionResponse",
    "build_vlm_transcription_messages",
]
