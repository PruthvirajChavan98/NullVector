# Title

PageIndex Import 03: Description-Based Document Selection

## Status

`recommended`

## Why This Comes From PageIndex

PageIndex treats LLM-generated document descriptions as a lightweight outer routing layer for collections without clean metadata.

- PageIndex evidence:
  - `/home/pruthvi/projects/github/PageIndex/tutorials/doc-search/description.md`
    - describes generating a one-sentence description per document
    - uses an LLM to pick relevant document IDs from the description list
  - `/home/pruthvi/projects/github/PageIndex/pageindex/utils.py`
    - contains `generate_doc_description(...)`

The PageIndex concept to import is a collection-level router over document descriptions, not the exact prompt wording.

## Current NullVector State

NullVector does not currently expose collection-level document profiles or selection.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/src/nullvector/domain/retrieval.py`
    - retrieval models are document-scoped
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/service.py`
    - searches one corpus at a time
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/qa.py`
    - answers from retrieval hits after a document is already selected
  - `/home/pruthvi/projects/NullVector/src/nullvector/tree/service.py`
    - persists node cards and summaries that can support a document profile

This spec assumes the document description artifact from Doc 01 exists.

## User Problem And Outcome

When metadata is incomplete or unavailable, users still need a fast way to pick the best documents to search. Description-based routing is especially useful for:

- small and medium collections
- diverse documents where titles alone are weak signals
- human-in-the-loop review workflows

The desired outcome is:

- generate or load one description per document
- present those descriptions to a selector
- return a small set of candidate `document_id`s before full retrieval

## Proposed Capability

Add a collection-level selection service that ranks documents using their persisted `DocumentDescription` artifacts.

The v1 system should:

- consume prebuilt description artifacts
- support LLM-based document selection
- support deterministic fallback scoring over description text when a gateway is unavailable
- return ranked candidate documents with reasons

## Interfaces And Types

Add:

- `DocumentDescriptionRecord`
  - `document_id`
  - `display_name`
  - `description_text`
  - `description_manifest_path`
- `DescriptionSelectionRequest`
  - `query`
  - `descriptions`
  - `limit`
- `DescriptionSelectionResponse`
  - `candidates`
  - `selection_mode`
    - `llm`
    - `deterministic_fallback`
- `DescriptionSelectionCandidate`
  - `document_id`
  - `score`
  - `reason`

Add service:

- `DescriptionSelectionService`
  - `select(request: DescriptionSelectionRequest) -> DescriptionSelectionResponse`

The service should live beside metadata selection in the retrieval layer.

## End-to-End Data Flow

1. Caller loads or supplies `DocumentDescriptionRecord`s for a collection.
2. `DescriptionSelectionService` builds a compact candidate set prompt or fallback scoring input.
3. If a gateway is present:
   - ask for a typed list of relevant `document_id`s and reasons
4. If no gateway is present:
   - use deterministic term overlap or ranker-style scoring over descriptions
5. Return ranked candidates.
6. Callers feed the selected `document_id`s into the existing retrieval pipeline.

The service never opens PDFs, reads full tree artifacts, or runs QA itself.

## Storage And Artifact Impact

This feature primarily consumes Doc 01 artifacts rather than creating new per-document ones.

Optional collection artifacts:

- `document-selection/description-index.jsonl`
- `document-selection/description-selection-results.json`

If persisted, these should be run-scoped selection artifacts, not changes to the source description manifests.

## LLM And Prompt Boundary

The selector prompt must accept:

- raw user query
- a bounded list of `{document_id, display_name, description_text}`

The typed response model should include:

- ordered candidate IDs
- one short reason per candidate

Guardrails:

- candidate list size must be capped
- no free-form prose-only outputs
- deterministic fallback must exist for environments without live gateway access

## Failure Modes And Guardrails

- If descriptions are missing, the service should refuse to run rather than trying to infer them ad hoc.
- If the description list is too large for one prompt, the service must shard candidates and merge results deterministically.
- If the gateway returns an unknown document ID, fail validation.
- If the gateway is unavailable, deterministic fallback must still produce a best-effort ranking.

## Testing And Acceptance

Implementation must include:

- unit tests for deterministic fallback ranking
- unit tests for shard-and-merge behavior
- integration test with typed gateway output validation
- notebook coverage in `notebooks/progress.ipynb` showing:
  - description artifact build
  - description selection over multiple documents
  - retrieval invoked only on selected candidates

Acceptance criteria:

- the selector can rank a collection using only persisted descriptions
- invalid gateway outputs are rejected
- deterministic fallback behaves sensibly on small collections

## Rollout Order

Depends on Doc 01.

Recommended order:

1. ship document descriptions
2. ship description selection service
3. later combine with metadata and semantic prefilters in a unified document router

## Non-Goals

- no on-the-fly description generation inside the selector
- no evidence retrieval or answer synthesis
- no replacement for metadata selection when rich metadata exists
- no use of raw PageIndex-style prompt helpers outside the gateway
