"""Prompt builder for map-reduce chunk-level hierarchy synthesis."""

from __future__ import annotations

import json

from nullvector.domain.ledger import OutlineEntry
from nullvector.llm.types import LLMMessage, LLMRole


def build_chunk_hierarchy_messages(
    *,
    markdown_pages: tuple[str, ...],
    chunk_start_page: int,
    chunk_end_page: int,
    outline_entries: tuple[OutlineEntry, ...] = (),
    previous_last_section: str | None = None,
) -> tuple[LLMMessage, ...]:
    """Build prompt messages for one chunk of the map-reduce hierarchy synthesis.

    The chunk covers pages ``chunk_start_page`` through ``chunk_end_page``
    (inclusive, 0-indexed).  Only pages in that range are included in the prompt.
    """

    chunk_pages = markdown_pages[chunk_start_page : chunk_end_page + 1]

    chunk_outline = [
        {"title": e.title, "level": e.level, "page_index": e.page_index}
        for e in outline_entries
        if e.page_index is not None and chunk_start_page <= e.page_index <= chunk_end_page
    ]

    metadata = json.dumps(
        {
            "chunk_start_page": chunk_start_page,
            "chunk_end_page": chunk_end_page,
            "page_count": len(chunk_pages),
            "total_document_pages": len(markdown_pages),
            "outline_entries": chunk_outline,
            "previous_last_section": previous_last_section,
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )

    full_text = "\n\n---PAGE BREAK---\n\n".join(
        f"[Page {chunk_start_page + i}]\n{text}" for i, text in enumerate(chunk_pages)
    )

    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are a document structure analyst. "
                "You are analyzing a CHUNK of a larger document (not the full document). "
                "Given the Markdown transcription of these pages and optional PDF outline entries, "
                "identify the hierarchical section structure within this chunk. "
                "Return a JSON object with: "
                "'nodes' array — each node has: title (MUST be a non-empty string, NEVER null "
                "— if no heading is visible, derive a short descriptive title from the content), "
                "level (1=top, 2=subsection, etc.), "
                "start_page (0-indexed global page number), end_page (0-indexed, inclusive), "
                "and summary_hint (string or null — always include this field). "
                "Use global page indices (not chunk-local). "
                "Use the PDF outline entries as strong hints when available. "
                "Order nodes by their appearance in the document."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                f"Analyze this document chunk and return its hierarchical structure.\n\n"
                f"Metadata:\n{metadata}\n\n"
                f"Chunk text:\n{full_text}"
            ),
        ),
    )


__all__ = [
    "build_chunk_hierarchy_messages",
]
