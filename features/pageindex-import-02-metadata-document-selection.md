# Title

PageIndex Import 02: Metadata-Driven Document Selection Before Retrieval

## Status

`recommended`

## Why This Comes From PageIndex

PageIndex explicitly documents metadata search as the first-stage narrowing strategy for collections that are distinguishable by structured fields.

- PageIndex evidence:
  - `/home/pruthvi/projects/github/PageIndex/tutorials/doc-search/metadata.md`
    - recommends metadata-driven search
    - describes query-to-SQL style narrowing
  - `/home/pruthvi/projects/github/PageIndex/tutorials/doc-search/README.md`
    - promotes metadata search as a first-class document-search mode

The import for NullVector is not literal SQL generation. It is the outer retrieval pattern: narrow the candidate document set using metadata before any document-scoped retrieval or QA.

## Current NullVector State

NullVector retrieval is currently document-scoped.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/src/nullvector/domain/retrieval.py`
    - `RetrievalCorpus` is bound to one `document_id`
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/service.py`
    - `search(...)` works over one corpus or one persisted `document_id`
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/planner.py`
    - query planning extracts modality and structural intent, not collection-level document filters
  - `/home/pruthvi/projects/NullVector/src/nullvector/storage/postgres.py`
    - storage already supports document identifiers and persisted artifacts, which is a good base for a collection index

NullVector has strong single-document retrieval but no typed, first-class collection-selection layer.

## User Problem And Outcome

Users with many documents need a fast way to answer:

- which documents should be searched at all
- which documents satisfy metadata constraints like company, year, case type, product family, or jurisdiction

The desired outcome is:

- a collection-level selection stage that produces candidate `document_id`s
- support for both deterministic filters and LLM-assisted filter extraction
- no requirement to bypass NullVector’s typed contracts with raw SQL strings

## Proposed Capability

Add a metadata selection subsystem in Phase 04 that translates user queries into typed document filters, executes those filters over a metadata index, and returns ranked candidate documents for downstream retrieval.

The v1 system should support two entry modes:

- explicit structured filters supplied by the caller
- natural-language queries converted to a typed filter plan via the LLM gateway

The selector then returns an ordered candidate set of `document_id`s for later retrieval calls.

## Interfaces And Types

Add the following types under retrieval/domain:

- `DocumentMetadataRecord`
  - `document_id`
  - `display_name`
  - `attributes: dict[str, ScalarValue]`
- `DocumentFilterClause`
  - `field`
  - `operator`
    - `eq`
    - `in`
    - `contains`
    - `gte`
    - `lte`
  - `value`
- `MetadataSelectionPlan`
  - `raw_query`
  - `normalized_query`
  - `clauses`
  - `reasoning_summary`
- `DocumentSelectionCandidate`
  - `document_id`
  - `score`
  - `selection_reason`
  - `matched_metadata`
- `MetadataSelectionRequest`
  - `query`
  - `metadata_records`
  - optional `gateway`

Add services:

- `MetadataSelectionPlanner`
  - converts natural-language query to `MetadataSelectionPlan`
- `MetadataSelectionService`
  - executes a plan over a metadata collection

Do not generate SQL text in the core framework. If a Postgres-backed optimization is added, it should compile the typed clauses into backend queries internally.

## End-to-End Data Flow

1. Caller supplies:
   - a natural-language query or explicit filter clauses
   - a collection of `DocumentMetadataRecord`s or a store-backed index handle
2. If needed, `MetadataSelectionPlanner` uses the typed gateway to emit `MetadataSelectionPlan`.
3. `MetadataSelectionService` applies the filter clauses to:
   - an in-memory metadata collection, or
   - a Postgres-backed metadata index
4. The service returns ranked `DocumentSelectionCandidate`s.
5. Callers pass the chosen `document_id`s into existing retrieval flows.

The selector must stop at document narrowing. It does not itself run evidence retrieval or answer synthesis.

## Storage And Artifact Impact

Add a collection-level metadata index artifact family.

Suggested artifacts:

- `document-selection/metadata-index.jsonl`
- `document-selection/metadata-selection-plan.json`
- `document-selection/metadata-selection-results.json`

For Postgres, add a dedicated metadata table keyed by `document_id`, but keep the in-memory artifact format canonical so both backends share the same logical contract.

The metadata source of truth should remain caller-controlled. NullVector stores an index copy for retrieval orchestration; it does not become the canonical business system for metadata.

## LLM And Prompt Boundary

Use the gateway only for filter extraction when the caller provides natural language.

- gateway input:
  - natural-language query
  - allowed metadata fields
  - allowed operators
- gateway output:
  - typed `MetadataSelectionPlan`

Do not ask the gateway to emit backend-specific SQL. The gateway should emit a backend-agnostic filter plan that NullVector validates before execution.

## Failure Modes And Guardrails

- Unknown metadata fields must fail validation before execution.
- Unsupported operators must be rejected deterministically.
- If the natural-language planner emits an invalid plan, surface the typed gateway validation error.
- If zero candidates match, return an empty candidate list, not an exception.
- If metadata is missing for some documents, those documents remain selectable only through other selection modes; metadata selection should not infer missing fields.

## Testing And Acceptance

Implementation must include:

- unit tests for clause execution semantics
- unit tests for planner validation against allowed fields
- integration tests for in-memory and Postgres-backed selection
- notebook coverage in `notebooks/progress.ipynb` showing:
  - metadata index creation
  - query -> metadata selection
  - candidate `document_id`s passed into retrieval

Acceptance criteria:

- natural-language queries map to typed filter plans
- deterministic clause execution is backend-agnostic
- selection results are stable and auditable

## Rollout Order

Can be implemented independently.

Recommended order:

1. metadata types
2. in-memory executor
3. LLM-backed planner
4. Postgres optimization

This doc does not depend on document descriptions or semantic prefiltering.

## Non-Goals

- no raw SQL generation in prompts
- no replacement of existing document-scoped retrieval
- no automatic metadata extraction from PDFs in v1
- no ranking by content semantics; that belongs in the semantic prefilter doc
