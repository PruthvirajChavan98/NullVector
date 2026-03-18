# Title

PageIndex Import 01: Document Descriptions As First-Class NullVector Artifacts

## Status

`recommended`

## Why This Comes From PageIndex

PageIndex already treats document descriptions as a lightweight selection primitive.

- PageIndex evidence:
  - `/home/pruthvi/projects/github/PageIndex/pageindex/utils.py`
    - `create_clean_structure_for_description(...)`
    - `generate_doc_description(...)`
  - `/home/pruthvi/projects/github/PageIndex/pageindex/page_index.py`
    - adds `doc_description` when `if_add_doc_description == 'yes'`
  - `/home/pruthvi/projects/github/PageIndex/pageindex/page_index_md.py`
    - adds `doc_description` for Markdown trees
  - `/home/pruthvi/projects/github/PageIndex/tutorials/doc-search/description.md`
    - uses one-sentence descriptions as the outer document-selection layer

The core PageIndex idea worth importing is not the exact helper implementation. It is the product concept that every document can expose a short, differentiating description derived from its structure.

## Current NullVector State

NullVector already persists the ingredients needed to generate a robust description, but it does not currently expose a document-level description artifact.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/src/nullvector/tree/service.py`
    - persists committed nodes, node cards, and optional node summaries
  - `/home/pruthvi/projects/NullVector/src/nullvector/domain/tree.py`
    - `TreeBuildManifest` already has `node_cards_path` and `node_summaries_path`
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/build.py`
    - builds document-scoped retrieval corpora from tree + acquisition artifacts
  - `/home/pruthvi/projects/NullVector/src/nullvector/domain/retrieval.py`
    - retrieval is document-scoped, but there is no document-profile model

Today, the closest NullVector has is a set of node summaries and persisted RetrievalEvidence artifacts. There is no compact per-document profile that a higher-level selector can consume.

## User Problem And Outcome

Users working with more than one document need a lightweight way to understand and rank documents before running full retrieval. Without a document description artifact, they have to inspect raw manifests, titles, or full node summaries manually.

The desired outcome is:

- every tree-backed document can expose a concise human-readable description
- the description is generated from persisted tree artifacts, not ad hoc prompt text
- the description is stored as a typed artifact with provenance
- downstream selection systems can consume it without re-reading the full tree

## Proposed Capability

Add a new retrieval-adjacent artifact builder that produces a single document description per document from committed node cards and node summaries.

The v1 behavior is:

- input:
  - `acquisition_manifest_path`
  - `tree_manifest_path`
  - optional generation settings
- output:
  - a typed document description artifact
  - a typed manifest for that artifact
- generation source:
  - prefer node summaries when present
  - fall back to node cards if summaries are absent
  - never require raw provider payloads or direct prompt assembly by callers

The description should be a short paragraph or one-sentence summary optimized for document differentiation, not generic abstracting.

## Interfaces And Types

Add the following interfaces and types.

- `DocumentDescription`
  - fields:
    - `document_id`
    - `tree_run_id`
    - `source_manifest_paths`
    - `description_text`
    - `description_method`
      - `llm_from_summaries`
      - `llm_from_node_cards`
      - `deterministic_fallback`
    - `source_node_ids`
    - `settings_digest`
- `DocumentDescriptionManifest`
  - fields:
    - `document_id`
    - `description_run_id`
    - `description_path`
    - `artifact_root`
    - `source_tree_manifest_path`
    - `source_acquisition_manifest_path`
- `DocumentDescriptionRequest`
  - fields:
    - `acquisition_manifest_path`
    - `tree_manifest_path`
    - `description_run_id`
    - `settings`
- `DocumentDescriptionSettings`
  - fields:
    - `max_source_nodes`
    - `prefer_node_summaries`
    - `max_output_tokens`
    - `require_gateway`

Add a new service:

- `DocumentDescriptionBuilder`
  - `build(request: DocumentDescriptionRequest) -> DocumentDescriptionManifest`

Place the service in the retrieval layer, not the tree layer, because the output is meant for cross-document retrieval/orchestration rather than tree correctness.

## End-to-End Data Flow

1. Load the acquisition manifest and tree manifest from the existing `DocumentStore`.
2. Load node cards and node summaries referenced by the tree manifest.
3. Select the highest-signal source nodes:
   - root node if present
   - first-level headings
   - summarized leaves with highest span coverage
4. Build a compact description prompt payload from those persisted artifacts.
5. Call the existing typed LLM gateway with a structured response model.
6. Validate the response into `DocumentDescription`.
7. Persist:
   - `document-description.json`
   - `manifest.json`
8. Mark the description run complete through the existing store run lifecycle.

If the gateway is unavailable and `require_gateway=False`, use a deterministic fallback that concatenates the highest-signal node titles and the first available summary into a compact, machine-generated description.

## Storage And Artifact Impact

Use a new run type: `document_description`.

Persist the following artifacts through `DocumentStore`:

- `description/document-description.json`
- `description/manifest.json`
- optional prompt/debug payloads only if they are already consistent with gateway audit policy

Do not embed the description directly into `TreeBuildManifest` or `RetrievalManifest` in v1. Instead:

- keep it as its own artifact family
- allow later selection services to reference its manifest path

This keeps tree and retrieval contracts stable while still making document descriptions reusable.

## LLM And Prompt Boundary

All LLM generation must go through the existing `StructuredLLMGateway`.

- use a typed response model with:
  - `description_text`
  - optional `supporting_node_ids`
- no raw helper functions
- no cleanup-based JSON extraction
- no provider-specific prompt transport

Prompt inputs must be assembled from persisted node cards and summaries only. The builder must not reopen the source PDF or regenerate tree structure.

## Failure Modes And Guardrails

- If the tree manifest has neither node cards nor node summaries, fail loudly with a typed runtime error.
- If the gateway returns malformed output, surface the existing gateway validation failure.
- If summaries are missing, degrade to node-card-based generation rather than failing.
- If the description already exists for the same `(document_id, description_run_id, settings_digest)`, return the existing manifest idempotently.
- Never let a description run mutate or reinterpret canonical tree artifacts.

## Testing And Acceptance

Implementation must include:

- unit tests for source-node selection
- unit tests for deterministic fallback generation
- integration test that persists description artifacts end-to-end
- integration test that re-running the same request returns the existing manifest
- notebook coverage in `notebooks/progress.ipynb` showing:
  - tree build
  - description build
  - printed description artifact

Acceptance criteria:

- every completed description run yields a typed manifest
- generated descriptions can be loaded without reopening the document
- description generation is auditable through the gateway subsystem

## Rollout Order

Implement first.

This doc is the prerequisite for:

- description-based document selection
- any future collection-level document-profile index

It is independent of:

- metadata document selection
- Markdown ingestion

## Non-Goals

- no changes to core tree correctness logic
- no embedding generation
- no collection-wide selection in this doc
- no mutation of `TreeBuildManifest` or `RetrievalManifest` in v1
- no provider-specific shortcut APIs outside the typed gateway
