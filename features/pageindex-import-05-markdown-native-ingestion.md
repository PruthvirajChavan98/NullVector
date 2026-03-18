# Title

PageIndex Import 05: Markdown-Native Ingestion Path

## Status

`recommended`

## Why This Comes From PageIndex

PageIndex already exposes Markdown as a first-class input mode.

- PageIndex evidence:
  - `/home/pruthvi/projects/github/PageIndex/run_pageindex.py`
    - accepts `--md_path`
  - `/home/pruthvi/projects/github/PageIndex/pageindex/page_index_md.py`
    - implements `md_to_tree(...)`
    - supports thinning, node summaries, node text, and document descriptions
  - `/home/pruthvi/projects/github/PageIndex/README.md`
    - documents Markdown support explicitly

The import for NullVector is straightforward: authored Markdown should be able to enter the same artifact-driven pipeline as PDFs.

## Current NullVector State

NullVector is still shaped around deterministic PDF ingestion.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/docs/architecture.md`
    - explicitly describes NullVector as a CPU-first framework for deterministic PDF ingestion
  - `/home/pruthvi/projects/NullVector/src/nullvector/ingest/acquisition_service.py`
    - fingerprints PDFs, validates PDF runtime versions, and routes through PDF acquisition providers
  - `/home/pruthvi/projects/NullVector/src/nullvector/ingest/providers/native_pymupdf.py`
    - current acquisition provider is PDF-native
  - `/home/pruthvi/projects/NullVector/src/nullvector/domain/ledger.py`
    - already has ledger and substrate contracts that could host non-PDF text if normalized correctly

NullVector does not currently have a first-class Markdown source kind or acquisition provider.

## User Problem And Outcome

Users often have authored Markdown, policy documents, specs, and developer docs that do not need PDF parsing. Today, NullVector forces the pipeline to start from PDF assumptions even when the document is already structured as headings and paragraphs.

The desired outcome is:

- ingest Markdown directly
- produce the same downstream artifacts that later tree/retrieval phases expect
- preserve deterministic provenance and line anchoring

## Proposed Capability

Add a new acquisition provider family for authored Markdown sources.

The v1 assumptions:

- source documents are authored Markdown, not lossy PDF-to-Markdown conversions
- heading depth comes from `#`, `##`, `###`, and so on
- the acquisition stage produces normalized text pages and line anchors even if the source has no physical page concept

To preserve downstream compatibility, v1 should treat the Markdown source as a synthetic single-page or logical-page text substrate, with stable line offsets and heading anchors.

## Interfaces And Types

Add:

- `SourceDocumentKind`
  - `pdf`
  - `markdown`
- extend `AcquisitionRequest`
  - add `source_kind`
- new provider identity:
  - `markdown_native`
- `MarkdownAcquisitionProvider`
  - implements `AcquisitionProvider`
- `MarkdownAcquisitionSettings`
  - `heading_marker_style`
  - `max_logical_lines_per_page`
  - `split_on_thematic_breaks`

Implementation decision:

- keep the main acquisition orchestration path
- branch provider/runtime validation based on `source_kind`
- do not overload the PDF provider to “kind of” handle Markdown

## End-to-End Data Flow

1. Caller submits `AcquisitionRequest` with `source_kind='markdown'` and `provider_identity='markdown_native'`.
2. `MarkdownAcquisitionProvider` reads the Markdown file.
3. It parses:
   - headings
   - paragraph blocks
   - fenced code blocks
   - lists
   - tables where possible
4. It emits a canonical ledger and text substrate with:
   - synthetic page indices
   - stable line ordering
   - deterministic content spans
5. Existing tree build uses the acquisition manifest exactly as it already does for PDF-backed inputs.
6. Retrieval corpus building remains unchanged once the ledger/substrate contract is satisfied.

## Storage And Artifact Impact

Reuse the existing acquisition run structure.

Persist:

- source copy under `source/original.md`
- canonical ledger
- canonical text substrate
- acquisition manifest

Do not fabricate PDF-specific outline artifacts when the source is Markdown. Instead:

- set outline source explicitly to a Markdown-derived synthetic outline, or
- leave outline artifacts absent and rely on heading-derived synthesis

## LLM And Prompt Boundary

Markdown ingestion should be deterministic in v1.

- no LLM needed for Markdown parsing
- optional LLM summarization remains an existing later tree-stage concern
- if future Markdown cleanup is needed, it should be a separate bounded enhancement, not part of base ingestion

## Failure Modes And Guardrails

- Reject Markdown files with ambiguous heading structure only if the parsed hierarchy would violate tree contract assumptions.
- Preserve code fences and tables as text rather than trying to be clever with unsafe heuristics.
- Warn or fail when input appears to be machine-converted PDF Markdown with broken heading levels, depending on strictness settings.
- Do not invent physical page numbers; expose synthetic logical pages clearly in metadata.

## Testing And Acceptance

Implementation must include:

- unit tests for Markdown block parsing
- unit tests for heading-to-ledger projection
- integration test:
  - Markdown acquire
  - tree build
  - retrieval corpus build
- notebook coverage in `notebooks/progress.ipynb` showing a Markdown source end-to-end

Acceptance criteria:

- authored Markdown can enter the existing NullVector pipeline
- downstream tree/retrieval services do not need Markdown-specific branching
- acquisition artifacts remain deterministic and typed

## Rollout Order

Can be implemented independently of collection-selection features.

Recommended order:

1. acquisition request/source-kind changes
2. Markdown provider
3. tree-pipeline compatibility validation
4. retrieval corpus validation

## Non-Goals

- no support for arbitrary HTML or rich-text sources in this doc
- no promise that converted PDF Markdown will preserve original hierarchy
- no provider-specific OCR or VLM behavior for Markdown inputs
- no weakening of existing PDF ingestion guarantees
