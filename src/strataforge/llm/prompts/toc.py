"""Typed TOC-detection prompt builder for ambiguous leading pages."""

from __future__ import annotations

from nullvector.llm.types import LLMMessage, LLMRole


def build_toc_detection_messages(*, page_text: str) -> tuple[LLMMessage, ...]:
    """Build a bounded prompt asking whether a single page is a TOC page."""

    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "Decide whether the provided page text is a table of contents page. "
                "Use only the provided page text. "
                "Return the structured schema only."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                "Determine whether this page is a table of contents page. "
                "Respond with the typed schema only.\n\n"
                f"Page text:\n{page_text}"
            ),
        ),
    )
