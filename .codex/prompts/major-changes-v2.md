> Status note (2026-03-12): Phases A-J are now active in code. The repository now includes the
> additive v2 domain split, native-first acquisition runtime, projection generation, acquisition-
> backed tree builds, tokenizer-backed semantic services, multimodal attachment-only gateway
> scaffolding, observability event bus/subscribers, edge exporters, and legacy v1 parse-runtime
> isolation under `nullvector.compat.legacy_parse`.
>
> Validation evidence recorded for the F-J completion pass:
> - `bash .codex/bin/preflight-codex.sh`
> - `make format-check`
> - `make lint`
> - `make typecheck`
> - `uv run python scripts/run_progress_notebook.py --output notebooks/_artifacts/progress.phase-fj.executed.ipynb`
> - `make test`
> - result: `147 passed`

## 1. Executive judgment

Your target architecture is stronger than the current codebase on the big questions:

* it moves OCR/vendor coupling out of the framework core,
* it replaces implicit failure with typed incompleteness,
* it introduces provenance,
* it creates a proper boundary between ingestion and tree synthesis,
* it avoids polluting the core with LangChain,
* and it gives you a sane observability story.

But the current blueprint has five structural faults:

1. The “three tracks” are modeled too rigidly.
2. The Phase 02 boundary is described in two incompatible ways.
3. The ledger terminology is drifting.
4. The adapter protocol is not fully coherent yet.
5. The current code cannot support your proposed visual/VLM path without a second gateway refactor.

So the blueprint is valid as a direction, but not yet lock-ready as an implementation spec.

## 2. Validate blueprint against current code

### What the current code actually is

The current framework is built around a deterministic parse-run model:

* `nullvector/ingest/service.py` creates a `ParseRunManifest`
* per-page outputs are recorded in `PageLedgerRow`
* native extraction and optional local OCR are fused in the ingest substrate
* the tree pipeline consumes persisted text/rawdict artifacts from Phase 01
* `nullvector/tree/service.py` reconstructs `PageArtifacts` from those artifacts
* tree building directly consumes page text plus optional rawdict layout cues
* LLM usage exists only for text-based structured tasks:

  * repair
  * TOC detection/parsing
  * decomposition
  * summarization
  * verification assistance

This means the current architecture is not ingestion-provider neutral. It is parse-substrate centric.

### Where your blueprint matches the real problems

Your blueprint correctly identifies these current-code issues:

* `nullvector/ingest/ocr.py` hardwires local OCR into the core.
* `ParserSettings` contains OCR-specific fields:

  * `ocr_languages`
  * `tessdata_path`
  * `ocr_dpi`
* `PageLedgerRow` bakes in local OCR artifact paths and OCR-specific state.
* `nullvector/ingest/text.py` is not a pure profiler; it is an OCR routing engine.
* `nullvector/tree/service.py` reaches back into raw page extraction artifacts directly instead of consuming a cleaner synthesis boundary.
* `observability/__init__.py` is only a placeholder.
* there is no canonical multimodal ledger with provenance.
* there is no export boundary for LangChain/LlamaIndex.

All of that is correct.

### Where the blueprint conflicts with current implementation

The current tree pipeline depends on richer page structure than your current description of `TreeSynthesisView` allows.

Examples:

* `nullvector/tree/headings.py` uses rawdict-derived signals like `top_y` and `font_size`.
* `nullvector/tree/toc.py` computes `font_uniformity_signal()` from rawdict lines.
* `anchor_title_on_page()` depends on stable line anchoring and occurrence indices.
* verification logic relies on local page line boundaries and offsets.

So if the new `TreeSynthesisView` is truly stripped down to only “PageSpan, TextLines, InferredTokens”, you will lose signals the current tree builder actively uses.

The correct conclusion is not “the tree builder should see everything.”
The correct conclusion is:

Phase 02 must not consume provider-native payloads, but it still needs a normalized structural text-layout view rich enough to preserve line order, offsets, bbox/position, and trust metadata.

That is the first major correction.

## 3. What is logical and what is illogical

### Logical

These ideas are logically sound and should stay.

#### A. Remove local OCR from the framework core

This is correct. The current code couples framework correctness to machine-local Tesseract runtime state. That is the wrong boundary for an enterprise framework.

Delete local OCR from the core.

#### B. Represent incompleteness as typed data

Also correct.

A dense scanned page or diagram should not become a console warning or a silent quality drop. It should become a persisted, typed artifact like `UnresolvedRegion`.

That is the right enterprise move.

#### C. Preserve provenance per extracted unit

Also correct.

Native text, external OCR, and VLM-derived content are not equally trustworthy. Provenance cannot be a vague note in metadata. It has to be first-class.

#### D. Keep LangChain out of the core

Correct.

`LangChain Document` is too weak for your internal representation and too unstable to own the center of the framework.

#### E. Add an event bus

Correct.

That gives you CLI progress, structured cloud logging, and later orchestration hooks without contaminating the core business logic.

#### F. Selective external OCR for only unresolved pages or regions

This is not just logical; it is the right operating model.

For a 200-page document, doing native extraction across the whole document and routing only the problematic pages or regions to external OCR/VLM is more correct than forcing the whole document down one mode.

That earlier instinct of yours was right.

### Illogical or incomplete

These need correction.

#### A. The “three tracks” should not be exclusive document-level modes

This is the biggest issue.

A real enterprise document is mixed-modality:

* pages 1–120 may be clean native text
* pages 121–130 may be scanned inserts
* pages 131–150 may be charts/tables
* pages 151–200 may be native again

So “Track A vs Track B vs Track C” as mutually exclusive whole-document modes is too rigid.

The correct model is:

* native-first ingestion,
* complexity profiling per page or region,
* selective fallback/enrichment for unresolved pages or regions,
* provenance preserved per block.

You can still keep the three provider families conceptually, but operationally they must be composable, not exclusive.

#### B. Phase 02 cannot both ignore provenance and use provenance-weighted logic

Your blueprint says two different things:

* Phase 02 should be insulated from source/vendor metadata.
* Phase 02 should apply stricter validation if data came from a VLM.

Both cannot be true unless you define a normalized trust field in the projection.

The right fix is:

Phase 02 should not see vendor-native payloads or vendor-specific JSON.
But it should see normalized trust/provenance tiers needed for synthesis and verification.

For example:

* `trust_tier = native_exact`
* `trust_tier = external_ocr_high`
* `trust_tier = external_ocr_medium`
* `trust_tier = vlm_low`

That keeps the abstraction clean and still lets the tree builder behave differently when needed.

#### C. `CanonicalLedger` is underspecified

Right now the terms are drifting:

* “Unified Page Artifact”
* “CanonicalLedger”
* “PageArtifact”
* “ledger per page”
* “yield CanonicalLedger for each page”

That is not schema discipline yet.

You need one exact model.

The cleanest version is:

* `CanonicalDocumentLedger`

  * contains document metadata and ordered pages
* `CanonicalPage`

  * contains page metadata and ordered blocks/events
* `Block` variants

  * `TextBlock`
  * `TableArtifact`
  * `VisualArtifact`
  * `UnresolvedRegion`
* `PageEvent`

  * diagnostic machine-readable warnings
* `ExtractionProvenance`

Do not use `CanonicalLedger` ambiguously for both page and document.

#### D. Your adapter protocol is not coherent yet

You showed one pattern conceptually, but the details conflict.

You wrote both:

* “returns a `CanonicalLedger`”
* “yields a `CanonicalLedger` for each page parsed”

Those are different contracts.

For enterprise-grade determinism, the public contract should produce one normalized document ledger, not a stream of vaguely page-shaped ledgers.

If you want streaming internally, that is fine, but the stable public boundary should be document-level.

#### E. “PyMuPDF detects tables and converts them to Markdown” is too strong as a guarantee

This is not a safe contract statement.

PyMuPDF can support structural extraction in some cases, but table reconstruction quality is document-dependent. A framework contract should not promise reliable Markdown table extraction on arbitrary PDFs unless you are prepared to defend that in tests across messy documents.

The correct contract is:

* native provider may emit `TableArtifact` when deterministically recoverable,
* it may also emit `UnresolvedRegion` for visually table-like regions it cannot recover safely,
* optional Markdown projection can exist as a convenience field, not as the canonical truth.

#### F. VLM-only ingestion inside the core contradicts your adapter-boundary philosophy

Later in the discussion you corrected the vendor adapter stance: users should implement their own adapters.

That same logic applies to VLM ingestion.

If the core owns AWS/Azure/GCP/VLM adapters, you are back to provider coupling.

So the corrected stance should be:

* core owns the protocol and target schemas,
* users own external OCR/VLM adapters,
* framework may later provide cookbook examples outside the core.

#### G. Your visual enrichment plan is blocked by the current gateway contracts

This is a concrete code reality.

Current `LLMMessage` is text-only:

* `role`
* `content: NonEmptyStr`

Current provider adapters assume text-only structured-output requests.

So Phase 04 multimodal enrichment is not “missing later”; it is impossible under the current `llm/types.py` and `llm/providers/*` contracts.

That means visual enrichment is not just a new worker.
It requires a gateway v2 or a completely separate multimodal adapter protocol.

That is a real architectural dependency.

#### H. “Exact token counting via tiktoken” is not what the current code does

Current code in `nullvector/tree/summarize.py` uses:

* `estimate_token_count(text) = int(len(text.split()) * 1.3)`

So the blueprint claim that Phase 03 strictly uses exact token counts is aspirational, not current.

It is logical to add a tokenizer boundary.
It is illogical to pretend it already exists.

Also, if you want provider-neutrality, hard-binding the core to `tiktoken` is not automatically ideal. Better to define a tokenizer protocol and provide one or more implementations.

## 4. The corrected architecture that is actually consistent

This is the version I would lock.

### Phase 01: Native-first ingestion plus selective enrichment routing

Not “three exclusive tracks.”

Instead:

* `NativeIngestionProvider`

  * always runs first for PDFs the core can open
  * extracts native text, outlines, layout cues, tables when safe, image/visual regions, profiling signals
* `ComplexityProfiler`

  * marks unresolved pages/regions
* optional external enrichers

  * user-supplied adapters may enrich only unresolved pages/regions
* final output

  * `CanonicalDocumentLedger`

That lets you handle mixed documents correctly.

### Canonical ledger boundary

The framework core should own:

* `CanonicalDocumentLedger`
* `CanonicalPage`
* `PageMetadata`
* `TextBlock`
* `TableArtifact`
* `VisualArtifact`
* `UnresolvedRegion`
* `PageEvent`
* `ExtractionProvenance`

Every block must carry provenance.
Every unresolved region must carry a reason code and fallback recommendation.
Every page must preserve stable reading order.

### Projection boundary for Phase 02

Before tree synthesis, the ledger is projected into:

* `TreeSynthesisView`
* `SynthesisPage`
* `SynthesisLine`
* maybe `SynthesisTableTextProjection` when deterministic

This projection must preserve enough structure for Phase 02 to work:

* page index
* line text
* normalized offsets
* reading order
* occurrence index or stable anchor index
* normalized bbox/top_y
* normalized font size / layout cues when available
* trust tier / provenance class

It must not expose vendor-native JSON or image bytes.

### External adapters

Core owns only the protocol.

Users own:

* Textract adapter
* Azure adapter
* GCP adapter
* VLM adapter

You can ship cookbook examples later, not core implementations.

### Visual enrichment

Do not let free-form VLM output directly shape hierarchy by default.

Safer rule:

* VLM can enrich `VisualArtifact` or `UnresolvedRegion` into structured visual insights,
* those insights attach to nodes later,
* they do not automatically become structural headings unless they pass stronger verification.

That avoids hallucinated tree nodes.

## 5. Specific contradictions between current code and target blueprint

These are the concrete mismatches you need to account for.

### `PageLedgerRow` is the wrong long-term core artifact

Current `PageLedgerRow` in `domain/models.py` is tightly bound to:

* OCR mode
* OCR paths
* native vs OCR text paths
* render artifact paths
* per-page text hash fields tied to local extraction pipeline

That is too ingestion-engine specific for your new architecture.

It should not survive as the main framework boundary.

### `ParserSettings` is overloaded and wrong for the new direction

It currently mixes:

* native extraction settings
* OCR runtime settings
* version pinning
* sampling policy

This should become separate config families, for example:

* `NativeIngestionSettings`
* `ProfilingSettings`
* `TreeSettings`
* maybe `ArtifactSettings`

### Rawdict sampling is too weak for the new synthesis boundary

Current code only persists native rawdict every N pages:

* `sample_native_rawdict_every_n_pages`

That means layout cues are incomplete by design.

For a stable enterprise structural pipeline, sampling rawdict every 10 pages but then using layout cues in heading/TOC logic is not ideal.

A better architecture is:

* derive a normalized lightweight line-layout artifact for every page,
* discard bulky rawdict if you want,
* but keep the normalized per-line features needed for synthesis.

### Tree modules currently consume ingestion artifacts directly

`tree/service.py` reconstructs `PageArtifacts` from Phase 01 text/rawdict files.

That is exactly the coupling your new architecture is trying to eliminate.

### Multimodal support is absent in the gateway

The current `llm` package cannot support image inputs.
So your Phase 04 vision path must either:

* be deferred,
* or force a gateway redesign.

## 6. Refactor phases

This is the enterprise-grade sequence. Not patchwork, not random edits.

### Phase 0: Lock vocabulary and invariants

Before code changes, lock these terms permanently:

* `CanonicalDocumentLedger`
* `CanonicalPage`
* `TreeSynthesisView`
* `UnresolvedRegion`
* `ExtractionProvenance`
* `PageEvent`
* `TrustTier`

Also lock the invariants:

* native-first is the default for PDFs
* local core does no OCR
* unresolved content is typed data, not console text
* external OCR/VLM lives behind user-owned adapters
* Phase 02 consumes projection, not provider payloads
* LangChain/LlamaIndex exist only at export boundary

Without this phase, the implementation will drift.

### Phase 1: Split domain models

Current `nullvector/domain/models.py` is too monolithic.

Split it into at least:

* `domain/common.py`
* `domain/ledger.py`
* `domain/tree.py`
* `domain/gateway.py`
* `domain/events.py`

Move old OCR and page-ledger models out of the future core path.

### Phase 2: Introduce v2 ingestion protocols in parallel

Add new modules such as:

* `ingest/protocols.py`
* `ingest/providers/native_pymupdf.py`
* `ingest/profiling.py`
* `ingest/projection.py`
* `ingest/merge.py`

At this phase, do not delete the old pipeline yet.
Build the new boundary alongside it and prove parity.

That is not patchwork. That is controlled cutover.

### Phase 3: Build the native non-OCR provider

Refactor current `ingest/service.py`, `ingest/text.py`, `ingest/outline.py`, and `ingest/fingerprint.py` into:

* fingerprinting
* native extraction
* layout normalization
* complexity profiling
* artifact persistence

Delete all local OCR invocation from the provider path.

### Phase 4: Define canonical ledger persistence

Refactor `ingest/artifacts.py` so Phase 01 writes:

* document manifest
* canonical ledger artifact
* native outline artifacts
* normalized line-layout artifacts
* event stream artifacts

Stop treating `page-ledger.jsonl` as the central long-term boundary.

### Phase 5: Projection layer before tree synthesis

Implement:

* ledger → `TreeSynthesisView`

This is mandatory.

Do not let `tree/service.py` load raw extraction payloads directly anymore.

### Phase 6: Refactor tree modules to consume the projection

Refactor:

* `tree/headings.py`
* `tree/anchors.py`
* `tree/toc.py`
* `tree/toc_reconcile.py`
* `tree/verify.py`

so they operate on synthesis primitives, not ingestion artifacts.

Keep:

* hierarchy assembly logic
* reconciliation logic
* verification structure

Refactor only the input boundary.

### Phase 7: Clean up summarization and decomposition

Current:

* `tree/summarize.py`
* `tree/decompose.py`

These can mostly stay, but should depend on projected or committed tree content rather than raw parse artifacts.

Add a tokenizer boundary here if you want exact token budgeting.

### Phase 8: Observability event bus

Turn `observability/` from placeholder into:

* event types
* publisher
* subscriber protocol
* CLI subscriber
* JSON logger subscriber

Emit events at:

* ingestion started/completed
* page profiled
* unresolved region emitted
* tree strategy selected
* node verified
* node summarized
* visual enrichment completed

### Phase 9: Export boundary

Add exporters outside the core domain logic, for example:

* `export/langchain.py`
* `export/llamaindex.py`

Do not import those ecosystems anywhere central.

### Phase 10: Delete the legacy OCR-centric substrate

Only after parity and cutover:

Delete or retire:

* `ingest/ocr.py`
* OCR-related enums and fields
* OCR runtime errors
* OCR-specific manifest fields

That is the final cleanup.

## 7. Map old modules to new architecture

Here is the concrete module-by-module map.

### Keep, but refactor

`nullvector/ingest/fingerprint.py`

* Keep.
* Still useful for source identity and idempotency.

`nullvector/ingest/outline.py`

* Keep.
* Still belongs in native ingestion.
* It becomes part of the native provider, not the whole ingestion architecture.

`nullvector/ingest/artifacts.py`

* Keep conceptually.
* Refactor to persist the canonical ledger and v2 manifests.

`nullvector/tree/hierarchy.py`

* Mostly keep.
* The hierarchy assembly logic is still valuable.
* It should consume projected candidates, not parse-ledger artifacts.

`nullvector/tree/strategy.py`

* Keep.
* Strategy orchestration remains useful.

`nullvector/tree/decompose.py`

* Keep with boundary cleanup.
* It already follows deterministic-first logic, which is good.

`nullvector/tree/summarize.py`

* Keep with tokenizer refactor.
* Current architecture is fine conceptually.

`nullvector/tree/verify.py`

* Keep but make provenance-aware.
* Verification should be able to weight trust tiers.

`nullvector/llm/*`

* Keep as the text structured gateway.
* But it is not enough for multimodal Phase 04 as currently designed.

### Keep, but move responsibility

`nullvector/tree/toc.py`

* Keep, but it must consume normalized synthesis lines/layout cues.

`nullvector/tree/toc_reconcile.py`

* Keep, same reason.

`nullvector/tree/headings.py`

* Keep the scoring logic.
* Replace raw Phase 01 artifact dependency with synthesis primitives.

`nullvector/tree/anchors.py`

* Keep after the new line/offset model is stable.

### Delete or retire

`nullvector/ingest/ocr.py`

* Delete from core.

`MissingOcrRuntimeError`

* Delete or retire.

`ParseErrorCode.MISSING_OCR_RUNTIME`

* Delete or retire.

`OcrMode`

* Delete from core ingestion domain.

Any OCR-specific artifact fields in `PageLedgerRow`

* Retire with the old ledger.

### Split and redesign

`nullvector/domain/models.py`

* Split aggressively.
* It is doing too much.

`nullvector/ingest/service.py`

* Split into:

  * native provider
  * ingestion orchestrator
  * ledger merger
  * manifest writer

`nullvector/ingest/text.py`

* Rename and refactor into profiling/layout normalization logic.
* Stop making OCR decisions.

`nullvector/tree/service.py`

* This becomes the main Phase 02 orchestrator over `TreeSynthesisView`, not over parse artifacts.

### New modules you need

At minimum:

* `domain/ledger.py`
* `domain/events.py`
* `ingest/protocols.py`
* `ingest/providers/native_pymupdf.py`
* `ingest/profiling.py`
* `ingest/projection.py`
* `ingest/merge.py`
* `observability/bus.py`
* `observability/subscribers.py`
* `export/langchain.py`
* `export/llamaindex.py`
* optionally `tree/tokens.py`

## 8. The corrected answer to your earlier selective-OCR question

You were not going wrong.

Your instinct was correct.

For a 200-page document, the correct framework behavior is:

1. parse the whole document natively first,
2. detect which pages or regions are unresolved,
3. preserve native results where they are good,
4. selectively enrich only unresolved pages or regions using external OCR or VLM,
5. merge enriched blocks back into the canonical ledger with strict provenance,
6. project that merged ledger into the tree synthesis view.

That is substantially better than:

* running whole-document OCR,
* or pretending one document must belong to one single track.

The only correction is this:
do not think in terms of “OCR the page” only. In enterprise documents, unresolved content is often regional, not page-wide. So your model should support both page-level and region-level fallback.

## 9. Non-negotiable design rules I would lock now

These should be formal.

1. Native extraction is authoritative wherever it exists and is not flagged unresolved.
2. External OCR may replace or fill only unresolved pages or regions unless explicitly configured otherwise.
3. VLM enrichment does not automatically become structural text truth.
4. Phase 02 sees normalized trust tiers, not vendor-native payloads.
5. The framework core ships protocols and schemas, not cloud vendor adapters.
6. Incompleteness is persisted as artifacts and events, never only as logs.
7. Exporters live at the edge, never in the core domain.
8. Tree synthesis must consume a stable projected view, not raw ingestion artifacts.
9. Layout cues required for headings/TOC must be normalized and preserved for all pages, not sampled sparsely.
10. Terminology must be locked before implementation begins.

---

Yes. Here is the architecture I would lock for NullVector.

This is not a loose concept note. It is a concrete framework architecture with boundaries, execution flow, domain contracts, module layout, and migration strategy from your current codebase.

# 1. The architectural position

NullVector should become a document-to-structured-knowledge framework with four strict internal boundaries:

1. **Acquisition boundary**
   Reads a source and produces a typed, provider-neutral canonical ledger.

2. **Synthesis boundary**
   Projects the ledger into a normalized structural view for hierarchy construction.

3. **Semantic boundary**
   Runs summarization, decomposition, verification, and optional multimodal enrichment over committed nodes.

4. **Export boundary**
   Projects committed NullVector-native outputs into downstream ecosystem objects such as LangChain or LlamaIndex, without polluting the core.

The central correction is this:

**NullVector must not model ingestion as one exclusive whole-document “track.”**
It must model ingestion as **native-first acquisition plus selective per-page or per-region enrichment**, with explicit provenance attached to every emitted block.

That is the enterprise-grade architecture.

---

# 2. Core architectural principles

These are the rules I would treat as non-negotiable.

## 2.1 Native-first, never OCR-first

The framework first attempts deterministic native extraction wherever possible. It does not invoke local OCR inside the core.

## 2.2 Incompleteness is data

If a page or region cannot be resolved confidently, the framework emits a typed unresolved artifact. It never silently degrades and never relies on console warnings as the system of record.

## 2.3 Provenance is first-class

Every extracted block must know:

* where it came from,
* how it was produced,
* how trustworthy it is,
* and whether it is grounded in native document structure.

## 2.4 Phase 02 does not consume provider payloads

The tree builder must never parse AWS/Azure/GCP/VLM JSON. It consumes only a NullVector-owned structural projection.

## 2.5 External provider logic belongs outside the core

The framework owns:

* protocols,
* schemas,
* validators,
* mergers,
* projections.

Users own:

* Textract adapters,
* Azure Document Intelligence adapters,
* GCP Document AI adapters,
* VLM adapters.

## 2.6 Exporters live at the edge

LangChain, LlamaIndex, vector DB helpers, and app-specific orchestration remain external projections of NullVector-native objects.

## 2.7 Typed events, not ad hoc logs

All runtime observability must flow through a typed event bus.

---

# 3. End-to-end runtime lifecycle

## Phase 01 — Acquisition and profiling

Inputs:

* source PDF or equivalent source handle
* optional external enrichers supplied by the user
* acquisition settings

Outputs:

* `CanonicalDocumentLedger`
* acquisition manifest
* acquisition events

What happens:

* fingerprint the source
* run native extraction
* detect outline
* normalize page-local line/layout structures
* profile each page and region for unresolved content
* optionally merge user-provided enrichments only into unresolved regions/pages
* persist canonical ledger

## Phase 02 — Structural synthesis

Inputs:

* `CanonicalDocumentLedger`

Outputs:

* `TreeSynthesisView`
* heading candidates
* hierarchy build artifacts
* committed `NodeCard`s
* verification report

What happens:

* project the ledger into synthesis-safe primitives
* score heading candidates
* choose hierarchy strategy
* build and repair hierarchy
* verify title grounding and span validity
* commit verified nodes only

## Phase 03 — Semantic compression

Inputs:

* committed nodes
* synthesis view / source excerpts
* LLM gateway

Outputs:

* node summaries
* keywords
* decomposition artifacts
* verification assists

What happens:

* decompose oversized leaf nodes
* summarize leaf nodes bottom-up
* summarize parent nodes bottom-up
* persist audit and usage artifacts

## Phase 04 — Multimodal enrichment

Inputs:

* unresolved visual regions
* visual artifacts flagged for enrichment
* user-supplied VLM enricher or multimodal gateway

Outputs:

* structured visual insights
* visual-to-node attachments
* enrichment audit

What happens:

* identify unresolved visual regions mapped to nodes
* invoke user-owned visual enrichment adapters
* attach structured insights to nodes as non-authoritative enrichments

## Phase 05 — Export

Inputs:

* committed enriched `NodeCard`s

Outputs:

* NullVector-native export artifacts
* edge projections to LangChain/LlamaIndex/etc.

What happens:

* project node cards into downstream app objects
* preserve source anchors and provenance in metadata

---

# 4. The corrected ingestion model

Do not keep “Track A / B / C” as mutually exclusive whole-document tracks.

Use this model instead:

## 4.1 Acquisition modes

### Mode A — Native acquisition

Framework-owned.
Uses PyMuPDF and deterministic local extraction only.

Produces:

* native text blocks
* line/layout signals
* outline artifacts
* image/table/visual detections
* unresolved regions where native extraction is insufficient

### Mode B — External enrichment

User-owned.
Takes unresolved pages or regions and returns canonical blocks.

Examples:

* AWS Textract page enrichment
* Azure page enrichment
* GCP page enrichment

### Mode C — Visual enrichment

User-owned.
Takes unresolved visual regions or image-derived artifacts and returns structured visual interpretations.

Examples:

* chart summary
* schematic labels
* diagram legend understanding
* table readout when native extraction failed

## 4.2 Why this is correct

Because enterprise documents are mixed:

* some pages are native text,
* some are scanned,
* some are diagrams,
* some are hybrid.

A document-level exclusive mode is too blunt.
Per-page and per-region enrichment is the only architecture that scales cleanly.

---

# 5. The core data model

This is the center of the framework.

## 5.1 `CanonicalDocumentLedger`

The framework’s authoritative ingestion boundary.

Suggested shape:

* `ledger_version`
* `document_id`
* `source_fingerprint`
* `source_metadata`
* `acquisition_manifest`
* `pages: tuple[CanonicalPage, ...]`
* `document_events: tuple[DocumentEvent, ...]`

This is the stable contract between acquisition and all downstream phases.

## 5.2 `CanonicalPage`

Each page contains:

* `page_index`
* `page_label`
* `width`
* `height`
* `rotation`
* `native_available: bool`
* `blocks: tuple[PageBlock, ...]`
* `events: tuple[PageEvent, ...]`

`PageBlock` is a tagged union.

## 5.3 Page block variants

### `TextBlock`

Fields:

* `block_id`
* `bbox`
* `content`
* `reading_index`
* `line_count`
* `word_count`
* `provenance`
* `grounding`

### `LineBlock`

You may optionally persist line-level artifacts directly if you want direct synthesis projection and stable offsets without reconstructing later.

Fields:

* `line_id`
* `bbox`
* `content`
* `reading_index`
* `occurrence_index`
* `top_y`
* `font_size`
* `font_family_hint`
* `provenance`

### `TableArtifact`

Fields:

* `table_id`
* `bbox`
* `reading_index`
* `cells` or `rows`
* `markdown_projection: str | None`
* `provenance`
* `grounding`

### `VisualArtifact`

Fields:

* `visual_id`
* `bbox`
* `reading_index`
* `kind_hint`
* `image_ref`
* `needs_enrichment: bool`
* `provenance`

### `UnresolvedRegion`

Fields:

* `region_id`
* `bbox`
* `reason_code`
* `severity`
* `recommended_fallback`
* `reading_index: int | None`
* `provenance`

This is the formal typed incompleteness contract.

## 5.4 `ExtractionProvenance`

Every block must carry this.

Suggested fields:

* `source_track`

  * `native`
  * `external_ocr`
  * `visual_enrichment`
* `producer_name`

  * `pymupdf`
  * `aws_textract`
  * `azure_docint`
  * `gcp_docai`
  * `custom_vlm_adapter`
* `producer_version: str | None`
* `confidence: float | None`
* `grounded_in_native_metadata: bool`
* `grounded_in_bbox: bool`
* `content_authoritativeness`

  * `authoritative`
  * `supplemental`
  * `interpretive`
* `adapter_name: str | None`

## 5.5 `GroundingEvidence`

Separate from provenance.

Suggested fields:

* `has_native_text_anchor: bool`
* `has_page_bbox_anchor: bool`
* `has_layout_anchor: bool`
* `supporting_native_refs: tuple[str, ...]`

This distinction matters:

* provenance says where it came from,
* grounding says what hard evidence supports it.

---

# 6. The synthesis projection

This is the boundary protecting Phase 02.

## 6.1 `TreeSynthesisView`

This is derived from `CanonicalDocumentLedger` and contains only the primitives required for hierarchy construction.

Suggested shape:

* `document_id`
* `pages: tuple[SynthesisPage, ...]`
* `outline_entries`
* `projection_events`

## 6.2 `SynthesisPage`

Fields:

* `page_index`
* `page_label`
* `width`
* `height`
* `lines: tuple[SynthesisLine, ...]`
* `table_text_projections: tuple[SynthesisTextProjection, ...]`
* `trust_summary`
* `unresolved_regions: tuple[SynthesisUnresolvedRegion, ...]`

## 6.3 `SynthesisLine`

This must preserve enough structure for the current heading and TOC logic to remain strong.

Fields:

* `line_id`
* `content`
* `normalized_text`
* `casefold_punct_text`
* `page_index`
* `reading_index`
* `start_offset`
* `end_offset`
* `occurrence_index`
* `bbox`
* `top_y`
* `font_size`
* `layout_cues_available`
* `trust_tier`

That last field is critical.

## 6.4 `TrustTier`

Phase 02 should not see vendor-native JSON, but it should see normalized trust classes.

Suggested enum:

* `native_exact`
* `native_layout_backed`
* `external_ocr_high`
* `external_ocr_medium`
* `external_ocr_low`
* `visual_interpretive`

This lets Phase 02 behave differently without leaking provider specifics.

## 6.5 Why this projection matters

Current code uses:

* text lines
* rawdict-backed font/top_y
* local matching offsets
* repeated header/footer detection
* TOC-like line scoring

So the projection must preserve normalized versions of those signals, not discard them.

---

# 7. Framework package layout

This is how I would restructure the repo.

```text
nullvector/
  __init__.py

  constants.py

  domain/
    __init__.py
    common.py
    source.py
    ledger.py
    synthesis.py
    tree.py
    semantic.py
    events.py
    export.py

  acquisition/
    __init__.py
    protocols.py
    service.py
    fingerprint.py
    native/
      __init__.py
      pymupdf_provider.py
      outline.py
      layout.py
      tables.py
      visuals.py
    profiling/
      __init__.py
      page_complexity.py
      unresolved.py
    merge.py
    artifacts.py
    manifest.py
    projection.py

  tree/
    __init__.py
    service.py
    headings.py
    anchors.py
    hierarchy.py
    repair.py
    strategy.py
    toc.py
    toc_reconcile.py
    verify.py

  semantic/
    __init__.py
    summarize.py
    decompose.py
    enrich.py
    tokens.py

  llm/
    __init__.py
    text_gateway/
      __init__.py
      protocols.py
      service.py
      providers/
      prompts/
    multimodal_gateway/
      __init__.py
      protocols.py
      service.py

  observability/
    __init__.py
    bus.py
    subscriber.py
    events.py
    subscribers/
      rich_progress.py
      json_logger.py

  export/
    __init__.py
    langchain.py
    llamaindex.py

  api/
    __init__.py
    schemas.py
    service.py
```

This is materially cleaner than the current monolith in `domain/models.py` and the OCR-entangled `ingest/`.

---

# 8. The acquisition subsystem

## 8.1 Public protocol: `AcquisitionProvider`

Framework-owned.

Contract:

* accepts a source handle and acquisition settings
* returns a `CanonicalDocumentLedger`

This should be the main entry boundary for framework-owned acquisition.

## 8.2 Public protocol: `PageEnricher`

User-owned.

Contract:

* accepts a page or unresolved region payload
* returns canonical blocks that can be merged into the ledger

This is where AWS/Azure/GCP adapters fit.

## 8.3 Public protocol: `VisualEnricher`

User-owned.

Contract:

* accepts a visual artifact or unresolved region image crop
* returns structured visual insights or canonical supplemental blocks

This is where VLM adapters fit.

## 8.4 Framework service: `AcquisitionService`

Responsibilities:

* fingerprint source
* invoke native provider
* run complexity profiling
* identify unresolved pages/regions
* optionally invoke registered enrichers
* merge outputs deterministically
* persist ledger and manifest
* emit events

This replaces the current OCR-centric `ParserSubstrateService`.

---

# 9. Native provider design

This is the framework-owned fast path.

## 9.1 Responsibilities

* open document with PyMuPDF
* extract outline
* extract native text
* derive stable line/layout artifacts
* detect table-like structures where deterministic
* detect embedded images / visuals
* compute complexity/profile signals
* emit unresolved regions where text recovery is unsafe or incomplete

## 9.2 What it must never do

* invoke Tesseract
* invoke vendor OCR
* invoke a VLM
* silently pretend unresolved pages are successfully parsed

## 9.3 Native profiling output

Current `ingest/text.py` should evolve into a pure profiler.

It should emit typed reasons such as:

* `RASTER_PAGE_WITH_LOW_NATIVE_TEXT`
* `DENSE_VECTOR_CLUSTER`
* `POSSIBLE_SCANNED_TABLE`
* `LARGE_VISUAL_WITHOUT_TEXT`
* `LOW_TEXT_DENSITY_HIGH_IMAGE_COVERAGE`

These reasons become artifacts and events.

---

# 10. Merge semantics for enrichment

This needs to be formal.

## 10.1 Merge policy

External enrichment may:

* fill an unresolved region,
* supplement a low-trust region,
* optionally replace a non-authoritative block when explicitly configured.

Default policy:

* native authoritative content wins,
* enrichment fills gaps,
* interpretive content never overwrites authoritative native content automatically.

## 10.2 Region-level merging

The merger should work by:

* page index
* bbox overlap
* reading order window
* provenance policy

## 10.3 Conflict resolution

If two enrichers provide conflicting content:

* preserve both as distinct provenance-tagged supplemental blocks,
* emit a `MergeConflictEvent`,
* do not collapse them into one fabricated truth.

---

# 11. Tree architecture

Most of your current tree logic is salvageable.

## 11.1 Keep

* candidate extraction logic
* heading scoring logic
* hierarchy assembly
* trust-mode strategy
* TOC reconciliation
* decomposition
* verification
* summary pipeline

## 11.2 Change

All tree modules must consume `TreeSynthesisView`, not raw parse artifacts from `page-ledger.jsonl` plus ad hoc rawdict files.

## 11.3 Heading scoring

Keep the scoring framework but let it consume:

* normalized synthesis lines
* trust tiers
* layout cues
* TOC overlap
* repeated header/footer penalties

## 11.4 Verification

Verification should become provenance-aware:

* native-exact matches can pass more directly,
* external OCR-derived titles may require stricter local evidence,
* visual/interpretive content cannot become structural truth without stronger evidence.

---

# 12. Semantic subsystem

## 12.1 Summarization

Your current bottom-up model is good.

Refinements:

* summarize only committed nodes
* persist summary provenance and usage
* separate token estimation from tokenizer implementation

## 12.2 Tokenization boundary

Do not hardcode one tokenizer into the whole core without a boundary.

Define a tokenizer protocol:

* `estimate_tokens(text: str) -> int`
* `count_tokens(text: str) -> int`

Then provide implementations:

* heuristic estimator
* exact tokenizer adapter if installed

## 12.3 Decomposition

Keep deterministic-first decomposition.
Allow LLM assistance only for bounded subdivision within already committed nodes.

## 12.4 Visual enrichment

Do not let visual enrichment directly alter hierarchy unless explicitly run through a stricter verification path.

Normal case:

* enrichment attaches structured insights to nodes,
* it improves retrieval and summaries,
* it does not casually create new sections.

---

# 13. LLM architecture

Your current `llm/` package is good for text-only structured tasks, but it is not enough for multimodal.

## 13.1 Split the gateway into two subdomains

### Text structured gateway

Owns:

* repair
* TOC detection/parsing
* decomposition
* summarization
* verification assistance

This is close to your current `llm/`.

### Multimodal enrichment gateway

Owns:

* image-based or region-based structured interpretation
* visual artifact enrichment
* chart/table/schematic extraction assistance

This should be a separate protocol family because current `LLMMessage` is text-only and current provider adapters assume text-only request bodies.

## 13.2 Why split

Because text-structured prompts and multimodal region prompts are different enough that forcing them through one thin abstraction becomes ugly and brittle.

---

# 14. Observability architecture

This should become a real subsystem.

## 14.1 Event bus

Framework-owned publisher/subscriber bus.

## 14.2 Event categories

Examples:

* `SourceFingerprintComputed`
* `AcquisitionStarted`
* `PageNativeParsed`
* `PageProfiled`
* `UnresolvedRegionEmitted`
* `ExternalEnrichmentRequested`
* `ExternalEnrichmentMerged`
* `ProjectionCreated`
* `HierarchyStrategySelected`
* `NodeCommitted`
* `NodeVerificationFailed`
* `NodeSummarized`
* `VisualEnrichmentAttached`
* `ExportCompleted`

## 14.3 Subscribers

At least:

* rich/tqdm progress subscriber
* JSON logging subscriber

This gives you:

* local notebook / CLI progress,
* server-side structured logging,
* future metrics integration without coupling domain logic to logging frameworks.

---

# 15. Persistence and manifests

The current parse-run manifest pattern is useful, but the artifact model should change.

## 15.1 Acquisition manifest

Contains:

* source fingerprint
* acquisition settings digest
* acquisition provider identity
* enrichment providers used
* ledger artifact path
* outline artifact paths
* event stream path

## 15.2 Tree manifest

Contains:

* source ledger identity
* synthesis view identity
* tree settings digest
* committed hierarchy paths
* verification paths
* summary paths
* decomposition paths
* enrichment attachment paths

## 15.3 Why this is better

Because the canonical ledger becomes the primary Phase 01 output, not page-ledger rows tied to OCR internals.

---

# 16. Export boundary

This is where LangChain belongs.

## 16.1 NullVector-native outputs

Primary outputs remain:

* `NodeCard`
* `NodeSummary`
* source anchors
* provenance
* visual insights
* verification metadata

## 16.2 Edge exporters

Add methods or helpers like:

* `to_langchain_document()`
* `to_llamaindex_node()`

But only at the export layer.

Internally, never use those classes.

---

# 17. Security and enterprise concerns

This needs to be designed in early, not patched later.

## 17.1 Secrets

Framework core should never manage cloud credentials directly for user-owned adapters. Those remain in user systems.

## 17.2 Auditability

All LLM and enrichment operations should have:

* audit records,
* provider identity,
* request IDs,
* timestamps,
* redaction hooks.

## 17.3 Determinism

Native acquisition and tree synthesis should remain deterministic wherever possible. LLM and visual enrichment should be auditable and bounded.

## 17.4 PII controls

Add redaction hooks at:

* event emission,
* LLM audit persistence,
* export projection.

---

# 18. Migration from current codebase

This is the implementation order I would use.

## Phase A — lock schemas and terminology

Before touching logic:

* define `CanonicalDocumentLedger`
* define `CanonicalPage`
* define `TextBlock`, `TableArtifact`, `VisualArtifact`, `UnresolvedRegion`
* define `TreeSynthesisView`
* define `TrustTier`
* split `domain/models.py`

## Phase B — build v2 acquisition in parallel

Create the new acquisition stack alongside the old one.
Do not rip out the current parser immediately.

## Phase C — implement native provider

Refactor current:

* `ingest/service.py`
* `ingest/text.py`
* `ingest/outline.py`
* `ingest/fingerprint.py`

into:

* native provider
* profiler
* acquisition service
* canonical artifact persistence

## Phase D — projection layer

Implement ledger-to-synthesis projection before changing tree logic.

## Phase E — move tree to synthesis inputs

Refactor:

* `tree/headings.py`
* `tree/toc.py`
* `tree/toc_reconcile.py`
* `tree/verify.py`
* `tree/service.py`

to consume `TreeSynthesisView`.

## Phase F — tokenizer and semantic cleanup

Refactor summarization and decomposition onto cleaner semantic boundaries.

## Phase G — multimodal gateway

Introduce the separate multimodal protocol for Phase 04 enrichment.

## Phase H — observability bus

Replace placeholder observability package with typed events and subscribers.

## Phase I — exporters

Add LangChain/LlamaIndex edge exporters.

## Phase J — delete legacy OCR substrate

Only after parity:

* delete `ingest/ocr.py`
* remove OCR runtime config from parser settings
* retire OCR-specific error codes and artifact paths

---

# 19. Old-to-new module mapping

## Current modules to keep conceptually

* `ingest/fingerprint.py`
* `ingest/outline.py`
* `tree/hierarchy.py`
* `tree/strategy.py`
* `tree/decompose.py`
* `tree/summarize.py`
* `tree/verify.py`

These contain logic worth preserving.

## Current modules to redesign

* `domain/models.py`
* `ingest/service.py`
* `ingest/text.py`
* `tree/service.py`

## Current modules to retire

* `ingest/ocr.py`
* OCR-related settings and error pathways in the core

---

# 20. The architecture I would formally lock

This is the final concise form.

**NullVector is a native-first document framework that produces a provider-neutral canonical document ledger, represents unresolved content as typed artifacts, selectively merges user-owned external OCR or VLM enrichments at page or region granularity, projects the merged ledger into a synthesis-safe structural view for deterministic hierarchy construction, performs bounded semantic compression and optional multimodal enrichment over committed nodes, and exports the final node graph to external ecosystems only at the boundary.**

That is the architecture.
