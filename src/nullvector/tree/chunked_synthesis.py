"""Map-reduce chunked hierarchy synthesis for large documents."""

from __future__ import annotations

from nullvector.domain.gateway import (
    ChunkHierarchyResponse,
    HierarchySynthesisResponse,
    MergeHierarchyResponse,
)
from nullvector.domain.ledger import OutlineEntry
from nullvector.llm.prompts.chunk_hierarchy import build_chunk_hierarchy_messages
from nullvector.llm.prompts.merge_hierarchy import build_merge_hierarchy_messages
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest


def synthesize_chunked(
    *,
    gateway: StructuredLLMGateway,
    markdown_pages: tuple[str, ...],
    outline_entries: tuple[OutlineEntry, ...] = (),
    chunk_size: int = 10,
    chunk_overlap: int = 2,
) -> HierarchySynthesisResponse:
    """Run map-reduce hierarchy synthesis and return a unified response.

    **Map phase**: splits the document into overlapping chunks, invokes the
    gateway in parallel via ``invoke_many`` to produce per-chunk structural
    analyses.

    **Reduce phase**: feeds the chunk summaries (not full text) into a single
    merge call to produce the global hierarchy.
    """

    total_pages = len(markdown_pages)
    chunk_boundaries = _compute_chunk_boundaries(
        total_pages=total_pages,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    # --- Map phase: parallel chunk analysis ---
    chunk_requests: list[GatewayRequest[ChunkHierarchyResponse]] = []
    prev_last_section: str | None = None

    for start_page, end_page in chunk_boundaries:
        messages = build_chunk_hierarchy_messages(
            markdown_pages=markdown_pages,
            chunk_start_page=start_page,
            chunk_end_page=end_page,
            outline_entries=outline_entries,
            previous_last_section=prev_last_section,
        )
        chunk_requests.append(
            GatewayRequest(
                operation_name="chunk_hierarchy_synthesis",
                messages=messages,
                response_model=ChunkHierarchyResponse,
                temperature=0.0,
            )
        )

    # Cap concurrency to avoid overwhelming provider TPM limits.
    # Even with retry + backoff, concurrent threads create thundering-herd
    # retries that exhaust the budget.  Two workers keeps each wave under
    # typical 30K TPM free-tier limits (~6K tokens/request x 2 = ~12K).
    effective_workers = min(len(chunk_requests), 2)
    chunk_results = gateway.invoke_many(chunk_requests, max_workers=effective_workers)
    chunk_responses = tuple(r.output for r in chunk_results)

    # --- Reduce phase: merge chunk analyses ---
    merge_messages = build_merge_hierarchy_messages(
        chunk_responses=chunk_responses,
        total_pages=total_pages,
    )
    merge_request: GatewayRequest[MergeHierarchyResponse] = GatewayRequest(
        operation_name="merge_hierarchy_synthesis",
        messages=merge_messages,
        response_model=MergeHierarchyResponse,
        temperature=0.0,
    )
    merge_result = gateway.invoke(merge_request)

    return HierarchySynthesisResponse(nodes=merge_result.output.nodes)


def _compute_chunk_boundaries(
    *,
    total_pages: int,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[tuple[int, int], ...]:
    """Compute (start_page, end_page) pairs with overlap between chunks."""

    if total_pages <= 0:
        return ()

    step = max(1, chunk_size - chunk_overlap)
    boundaries: list[tuple[int, int]] = []
    start = 0
    while start < total_pages:
        end = min(start + chunk_size - 1, total_pages - 1)
        boundaries.append((start, end))
        start += step
        if end == total_pages - 1:
            break

    return tuple(boundaries)


__all__ = [
    "synthesize_chunked",
]
