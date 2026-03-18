# Title

PageIndex Import 04: Semantic Document Prefiltering Before NullVector Retrieval

## Status

`recommended`

## Why This Comes From PageIndex

PageIndex documents semantic search as an outer stage that finds promising documents before inner tree retrieval happens.

- PageIndex evidence:
  - `/home/pruthvi/projects/github/PageIndex/tutorials/doc-search/semantics.md`
    - describes chunk embeddings, document scoring, and selecting documents before retrieval
  - `/home/pruthvi/projects/github/PageIndex/tutorials/doc-search/README.md`
    - lists semantic search as a first-class document-search mode

The PageIndex import to NullVector is the staged architecture pattern: collection prefilter first, document retrieval second.

## Current NullVector State

NullVector has strong evidence retrieval inside a document but no built-in semantic collection router.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/build.py`
    - builds rich document-scoped corpora with `NODE_TEXT`, `NODE_SUMMARY`, page, table, and visual units
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/service.py`
    - searches one corpus or one `document_id` at a time
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/index.py`
    - current index types are still document-scoped

This means NullVector already has good document evidence units, but not a collection-level prefilter index over those documents.

## User Problem And Outcome

For large collections with weak metadata and noisy titles, metadata and description selection may not be enough. Users need an optional, more recall-oriented prefilter that can quickly shortlist documents for full retrieval.

The desired outcome is:

- index each document into a compact semantic proxy
- search those proxies to get candidate documents
- preserve NullVector’s single-document retrieval stack after candidate selection

## Proposed Capability

Add a pluggable collection-level prefilter engine that scores documents before document-scoped retrieval begins.

The v1 design should support:

- a deterministic lexical baseline
- an optional embedding-backed scorer behind a protocol boundary
- a stable document-level score aggregation contract

The core NullVector framework should own the interfaces and aggregation logic, but not hardcode one embedding vendor.

## Interfaces And Types

Add:

- `DocumentSemanticProxy`
  - `document_id`
  - `display_name`
  - `description_text`
  - `summary_text`
  - `keywords`
  - `source_unit_ids`
- `DocumentPrefilterHit`
  - `document_id`
  - `score`
  - `matched_proxy_fields`
- `DocumentPrefilterRequest`
  - `query`
  - `proxies`
  - `limit`
- `DocumentPrefilterEngine` protocol
  - `search(request) -> tuple[DocumentPrefilterHit, ...]`

Implementations:

- `LexicalDocumentPrefilter`
  - core deterministic implementation
- `EmbeddingDocumentPrefilter`
  - optional plugin implementation

Do not put provider-specific embedding logic in the retrieval core. Keep it behind a protocol.

## End-to-End Data Flow

1. Build one `DocumentSemanticProxy` per document from:
   - document description
   - top-level node summaries
   - selected keywords or titles
2. Persist the proxy index.
3. At query time, execute prefilter search over the proxy collection.
4. Return top candidate `document_id`s.
5. Run existing NullVector retrieval only on those candidates.

The score aggregation contract in v1 should be document-level only. It should not expose raw chunk vectors through the public API.

## Storage And Artifact Impact

Persist:

- `document-selection/semantic-proxy-index.jsonl`
- `document-selection/semantic-prefilter-results.json`

Optional backend-specific vector storage is allowed, but the canonical artifact must remain the document proxy representation so the system still has a deterministic baseline.

## LLM And Prompt Boundary

This feature should not require the LLM gateway for its core search path.

- gateway usage is optional only for:
  - query rewrite
  - explanation generation
- prefilter scoring must work without live LLM access

This keeps the prefilter usable for bulk routing and avoids forcing network LLM latency into the first-stage collection narrowing path.

## Failure Modes And Guardrails

- If no embedding engine is configured, lexical prefiltering must still work.
- If proxy artifacts are stale relative to the tree or description artifacts, fail with a manifest mismatch rather than silently using stale data.
- If document proxies are too sparse, fallback should still return a safe low-recall ranking instead of crashing.
- The prefilter must never pretend to answer the query; it only narrows candidates.

## Testing And Acceptance

Implementation must include:

- unit tests for proxy construction
- unit tests for lexical prefilter ranking
- protocol tests for optional embedding engines
- integration tests that connect prefilter hits to document-scoped retrieval
- notebook coverage in `notebooks/progress.ipynb` showing:
  - proxy build
  - prefilter selection
  - downstream retrieval on selected documents

Acceptance criteria:

- prefiltering reduces the candidate set without breaking downstream retrieval
- proxy artifacts are reusable across runs
- deterministic baseline remains functional without embeddings

## Rollout Order

Recommended order:

1. document descriptions
2. proxy builder
3. lexical prefilter
4. optional embedding protocol

This feature can coexist with metadata selection and description selection, and the eventual document router should choose among them.

## Non-Goals

- no replacement of document-scoped evidence retrieval
- no provider-specific embedding dependency in core NullVector
- no raw chunk-level vector index as the only artifact of record
- no implicit weakening of the “vectorless retrieval over structure” philosophy inside the main retrieval stage
