"""Prompt builder for the merge (reduce) step of map-reduce hierarchy synthesis."""

from __future__ import annotations

import json

from nullvector.domain.gateway import ChunkHierarchyResponse
from nullvector.llm.types import LLMMessage, LLMRole


def build_merge_hierarchy_messages(
    *,
    chunk_responses: tuple[ChunkHierarchyResponse, ...],
    total_pages: int,
) -> tuple[LLMMessage, ...]:
    """Build prompt messages for merging chunk-level hierarchy analyses.

    Receives the structural summaries from all chunks and asks the LLM to
    produce a single, unified document hierarchy.  The full document text is
    NOT included — only the per-chunk section lists and boundary notes.
    """

    chunks_data: list[dict[str, object]] = []
    for idx, chunk in enumerate(chunk_responses):
        nodes_data = [
            {
                "title": n.title,
                "level": n.level,
                "start_page": n.start_page,
                "end_page": n.end_page,
                "summary_hint": n.summary_hint,
            }
            for n in chunk.nodes
        ]
        chunks_data.append(
            {
                "chunk_index": idx,
                "nodes": nodes_data,
            }
        )

    payload = json.dumps(
        {
            "total_pages": total_pages,
            "chunk_count": len(chunk_responses),
            "chunks": chunks_data,
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )

    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are a document structure analyst performing a merge step. "
                "You have received structural analyses from multiple overlapping chunks "
                "of a document. Your task is to merge them into a single, unified "
                "hierarchical structure for the entire document. "
                "Rules: "
                "1. Merge sections that span chunk boundaries into one node — use "
                "overlapping page ranges to identify continuations. "
                "2. Deduplicate sections that appear in overlapping regions of adjacent chunks. "
                "3. Establish correct parent-child relationships based on level hierarchy. "
                "4. Preserve the original page ranges from the chunk analyses. "
                "Return a JSON object with a 'nodes' array. Each node has: "
                "title (MUST be a non-empty string, NEVER null — "
                "derive a descriptive title if none exists), "
                "level (1=top, 2=subsection, etc.), "
                "start_page (0-indexed), end_page (0-indexed, inclusive), "
                "and summary_hint (string or null — always include this field). "
                "Order nodes by their appearance in the document."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(f"Merge these chunk analyses into a unified document hierarchy.\n\n{payload}"),
        ),
    )


__all__ = [
    "build_merge_hierarchy_messages",
]
