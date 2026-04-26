"""Prompt builder for LLM-driven document hierarchy synthesis."""

from __future__ import annotations

import json

from nullvector.domain.ledger import OutlineEntry
from nullvector.llm.types import LLMMessage, LLMRole


def build_hierarchy_synthesis_messages(
    *,
    markdown_pages: tuple[str, ...],
    outline_entries: tuple[OutlineEntry, ...] = (),
) -> tuple[LLMMessage, ...]:
    """Build prompt messages for LLM hierarchy synthesis.

    Sends the VLM-transcribed Markdown pages plus any PDF outline entries
    and asks the LLM to return a structured JSON hierarchy.
    """

    outline_data = [
        {"title": e.title, "level": e.level, "page_index": e.page_index} for e in outline_entries
    ]

    pages_summary = []
    for i, page_text in enumerate(markdown_pages):
        preview = page_text[:500] if len(page_text) > 500 else page_text
        pages_summary.append({"page_index": i, "preview": preview, "length": len(page_text)})

    payload = json.dumps(
        {
            "page_count": len(markdown_pages),
            "outline_entries": outline_data,
            "pages": pages_summary,
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )

    full_text = "\n\n---PAGE BREAK---\n\n".join(
        f"[Page {i}]\n{text}" for i, text in enumerate(markdown_pages)
    )

    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are a document structure analyst. "
                "Given the Markdown transcription of a document and optional PDF outline entries, "
                "identify the hierarchical section structure. "
                "Return a JSON object with a 'nodes' array. Each node has: "
                "title (MUST be a non-empty string, NEVER null — if no heading is visible, "
                "derive a short descriptive title from the content), "
                "level (1=top, 2=subsection, etc.), "
                "start_page (0-indexed), end_page (0-indexed, inclusive), "
                "and summary_hint (brief section description, or null — "
                "always include this field). "
                "Order nodes by their appearance in the document. "
                "Use the PDF outline entries as strong hints when available. "
                "If no clear sections exist, return a single root node spanning all pages."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                f"Analyze this document and return its hierarchical structure.\n\n"
                f"Metadata:\n{payload}\n\n"
                f"Full document text:\n{full_text}"
            ),
        ),
    )


__all__ = [
    "build_hierarchy_synthesis_messages",
]
