"""Typed TOC parsing prompt artifacts."""

from __future__ import annotations

import json

from nullvector.llm.types import LLMMessage, LLMRole


def build_toc_parse_messages(*, toc_text: str) -> tuple[LLMMessage, ...]:
    """Build bounded messages for structured TOC text parsing."""

    payload = json.dumps(
        {"toc_text": toc_text},
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are parsing only the provided table-of-contents text into structured "
                "entries. Return only visible structure prefixes, titles, and page numbers. "
                "Do not invent missing lines, sections, or page numbers."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                "Return structured TOC entries with fields structure, title, and page_number "
                "using only this TOC text:\n"
                f"{payload}"
            ),
        ),
    )
