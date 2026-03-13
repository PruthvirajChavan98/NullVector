# Codex Prompt — Phase 04 Multimodal Parser Substrate (VLM-First, Tesseract-Deemphasized)

You are working on NullVector.

Mission:
Implement Phase 04 as a production-grade multimodal parser substrate that replaces Tesseract as the default recovery path and upgrades the tree pipeline to consume visually grounded document structure.

Primary objective:
Turn NullVector from a parser substrate with OCR fallback into a typed, auditable, VLM-first document-understanding framework.

Non-goals for this phase:
- do not build retrieval, serving APIs, or workflow orchestration
- do not add vector databases or chunk stores
- do not rewrite Phase 02 semantics unless required by multimodal grounding
- do not remove native PDF text extraction
- do not keep Tesseract on the default path

Core product position:
This framework is intended to compete directly with PageIndex-style OCR-free, vision-first document indexing. The implementation must therefore optimize for multimodal document structure, grounded page evidence, and typed artifact contracts rather than plain OCR replacement.

Architecture decision for Phase 04:
Use a VLM-first, native-text-reconciled approach.

This means:
1. native PDF text remains a low-level deterministic substrate when present
2. VLMs become the authoritative semantic/layout reader for:
   - scanned pages
   - mixed-content pages
   - heading detection
   - reading order
   - table and figure region understanding
   - repeated header/footer suppression
3. when native text exists, VLM outputs must reconcile back to persisted text and offsets where possible
4. when exact text-offset reconciliation is not possible, emit explicit visual anchors rather than inventing character-perfect offsets
5. Tesseract is moved to legacy/compat mode only and must not remain the default fallback

## Phase 04 scope split

### 04A — Multimodal contracts and artifact substrate
Add new typed multimodal contracts and artifact persistence without yet requiring end-to-end tree integration.

Create:
- `src/nullvector/vlm/__init__.py`
- `src/nullvector/vlm/types.py`
- `src/nullvector/vlm/errors.py`
- `src/nullvector/vlm/protocols.py`
- `src/nullvector/vlm/audit.py`
- `src/nullvector/vlm/service.py`
- `src/nullvector/vlm/providers/__init__.py`
- `src/nullvector/vlm/providers/noop.py`
- `src/nullvector/vlm/providers/openai_responses.py`
- `src/nullvector/vlm/providers/gemini_docs.py`
- `src/nullvector/vlm/prompts/__init__.py`
- `src/nullvector/vlm/prompts/transcription.py`
- `src/nullvector/vlm/prompts/layout.py`
- `src/nullvector/vlm/prompts/headings.py`

Extend `src/nullvector/domain/models.py` with new strict models:
- `PageRenderArtifact`
- `VisualBoundingBox`
- `VisualSpan`
- `VisualLine`
- `VisualBlock`
- `VisualTableRegion`
- `VisualFigureRegion`
- `ReadingOrderSegment`
- `VisualAnchor`
- `VLMTranscriptPage`
- `VLMLayoutPage`
- `VLMExtractionManifest`
- `VLMRequest`
- `VLMUsage`
- `VLMAttempt`
- `VLMFailureCategory`
- `VLMFailure`
- `VLMSuccess`
- `VLMProviderConfig`
- `OpenAIVLMProviderConfig`
- `GeminiVLMProviderConfig`

Rules for these contracts:
- all models must remain Pydantic v2 strict/frozen/extra-forbid, aligned with existing `StrataModel`
- no provider-native untyped JSON may cross the VLM boundary
- all raw provider payloads must be captured only in audit artifacts
- all page evidence must be representable either as:
  - exact text offsets in persisted page text, or
  - explicit visual anchors with bbox + quote + page index
- visual anchors must never pretend to be exact character offsets

Persist multimodal artifacts under parse roots in a deterministic layout:
- `pages/{page_index}/render.png`
- `pages/{page_index}/vlm.transcript.json`
- `pages/{page_index}/vlm.layout.json`
- `vlm/manifest.json`
- `vlm/audit/{request_id}.json`

### 04B — VLM provider adapters and page/document extraction
Implement the first real multimodal providers.

Provider order:
1. direct OpenAI Responses adapter
2. direct Gemini document adapter
3. noop scripted adapter for deterministic tests

Do not add Anthropic in the first execution pass unless the foundation is already stable.

Provider capability modes:
- `page_image_mode`
- `native_pdf_mode`

Requirements:
- OpenAI adapter must support page-image multimodal extraction with strict structured outputs
- Gemini adapter must support native PDF or equivalent document-mode extraction when available, plus structured outputs
- both adapters must normalize outputs into the same typed NullVector contracts
- unsupported provider capability paths must fail typed, not silently downgrade
- all failures must be typed and auditable:
  - validation failure
  - timeout
  - rate limit
  - network failure
  - provider refusal
  - auth failure
  - context length / size violation
  - unsupported capability
  - unknown provider failure

Do not use regex JSON repair.
Do not allow raw text-only provider output across the VLM boundary.
Do not silently fall back from provider-native strict extraction to loose prompt-only parsing.

### 04C — Parser substrate replacement
Refactor the ingest layer so Tesseract is no longer the default fallback.

Changes:
- add `src/nullvector/ingest/visual.py`
- either remove or deprecate `src/nullvector/ingest/ocr.py` from the default parse path
- update `src/nullvector/ingest/service.py`
- update `src/nullvector/ingest/text.py` only as needed to separate:
  - native PDF text analysis
  - multimodal escalation decisioning

Introduce a new decision model:
- `classify_visual_enrichment_need()`
- `VisualEnrichmentDecision`

Default policy:
- born-digital page with healthy native text and usable rawdict:
  - keep native extraction
  - do not invoke VLM unless layout ambiguity matters
- scanned page or image-heavy page:
  - skip Tesseract
  - render page image
  - invoke VLM transcript + layout extraction
- mixed-content page:
  - keep native text
  - invoke VLM for layout, region classes, and reading-order reconciliation

Phase 04 parser outputs must now include:
- native page text
- optional rawdict
- page render artifact
- optional VLM transcript artifact
- optional VLM layout artifact
- per-page provenance about which modality produced which evidence

### 04D — Tree pipeline multimodal upgrade
Upgrade the tree pipeline to consume visual structure.

Modify:
- `src/nullvector/tree/headings.py`
- `src/nullvector/tree/anchors.py`
- `src/nullvector/tree/verify.py`
- `src/nullvector/tree/service.py`
- `src/nullvector/tree/hierarchy.py` only when necessary

New heading candidate sources:
- native text
- rawdict/layout
- VLM transcript/layout

Add deterministic heading signals for multimodal scoring:
- font-scale band
- left-edge alignment band
- vertical whitespace isolation
- title-to-body transition confidence
- visual top-of-page position
- repeated header/footer recurrence using position + text
- table/figure caption suppression
- running-header suppression
- reading-order break strength

Candidate reconciliation rules:
- native text remains authoritative for literal character offsets when available
- VLM remains authoritative for region class and reading order
- when a VLM heading candidate matches persisted page text, align back to exact offsets
- when exact alignment fails, emit a visual anchor and preserve that explicitly
- do not fabricate offsets

Verification changes:
- title verification must support both text-local matching and visual-anchor verification
- verification artifacts must remain typed and auditable
- existing Phase 02 verification semantics must not be weakened

### 04E — Fixtures, notebook, and docs
Formalize multimodal fixtures and close out the phase with deterministic documentation artifacts.

Add synthetic multimodal fixtures under:
- `fixtures/phase04/inputs/`
- `fixtures/expected/phase04/`

Fixture policy:
- fixtures are curated synthetic artifacts for multimodal/tree edge cases
- they may include render images, transcript JSON, layout JSON, and parse manifests
- they are not required to be faithful dumps of a single provider response
- they must be as small and deterministic as possible

Notebook/doc requirements:
- update canonical `notebooks/progress.ipynb` to Phase 04
- add `notebooks/phase04_vlm_cookbook.ipynb`
- cookbook must include:
  - noop multimodal example
  - mocked OpenAI page-image example
  - mocked Gemini document example
  - native-text + VLM reconciliation example
  - tree-heading candidate example with visual anchors
- live cells, if any, must be env-gated and skipped in CI
- keep notebook structure tests for `progress.ipynb`

ADR/docs:
- add a new ADR for Phase 04 multimodal parser substrate
- update README with:
  - VLM provider selection
  - audit artifact paths
  - render/transcript/layout artifact meanings
  - Tesseract legacy-only status
  - env vars for OpenAI and Gemini adapters

## Required design rules

1. no regex JSON repair
2. no untyped provider output crosses the public VLM boundary
3. no silent fallback on parse failure
4. no fake text offsets from visual-only evidence
5. all retries and failures must be observable
6. all prompt/builders must request grounded output only
7. native text must be reconciled, not discarded
8. Tesseract must not remain on the default path
9. visual evidence must be persisted as auditable artifacts
10. page-level processing must remain deterministic and replayable from artifacts

## Public API requirements

The VLM boundary should mirror the quality bar of Phase 03.

Public service contract:
- a sync-first typed service is acceptable for this phase
- providers remain thin adapters
- core pipeline imports zero provider SDK specifics outside adapters

Recommended public shape:
- `VLMService.invoke_page(...) -> VLMSuccess[...]`
- `VLMService.invoke_document(...) -> VLMSuccess[...]`

or equivalent typed API, provided:
- typed request in
- typed validated success out
- typed exception on failure
- audit artifact available on both success and failure

## Integration strategy with existing code

Keep the existing parser/tree seams intact as much as possible.

Required compatibility outcomes:
- current Phase 01/02 tests that do not depend on OCR-specific behavior should remain green
- Phase 04 should add new multimodal capability without destabilizing parse-run and tree-run determinism
- when VLM is disabled and no visual enrichment is requested, born-digital native extraction should still work
- `NoopRepairEngine` behavior remains unchanged unless multimodal repair-specific work is explicitly required

## Test plan

Add unit tests for:
- visual anchor model validation
- exact text-offset reconciliation from VLM transcript to persisted page text
- duplicate heading occurrence anchoring with visual evidence
- repeated header/footer suppression using position + recurrence
- table caption vs heading disambiguation
- provider failure normalization
- noop multimodal provider scripted success/failure
- audit record generation and redaction

Add integration tests for:
- scanned-page fixture with Tesseract disabled by default still producing usable hierarchy artifacts
- born-digital fixture preserving exact native offsets while adding multimodal evidence
- mixed-content fixture producing table/figure regions and correct heading suppression
- OpenAI mocked adapter contract path
- Gemini mocked adapter contract path
- notebook execution for `progress.ipynb`
- notebook execution for `phase04_vlm_cookbook.ipynb`
- notebook structure/order checks for `progress.ipynb`

Add regression tests for:
- unchanged deterministic tree behavior on existing clean born-digital fixtures
- unchanged run-index determinism and artifact manifest stability
- unchanged verification strictness unless explicitly extended for visual anchors

## Validation required before completion

Run exactly:
- `bash .codex/bin/preflight-codex.sh`
- `make format-check`
- `make lint`
- `make typecheck`
- targeted multimodal unit tests
- targeted multimodal integration tests
- `make test`

Do not mark Phase 04 complete without all validations passing.

## Delivery contract

When done, return:
1. changed files
2. validation output
3. operational caveats
4. residual risks
5. any explicit deferred items that were intentionally left for Phase 05

## Execution priorities

Priority order:
1. strict contracts and artifact model
2. noop provider and deterministic tests
3. OpenAI page-image adapter
4. Gemini document adapter
5. parser substrate refactor to VLM-first
6. tree multimodal reconciliation
7. notebook/docs closeout

## Constraints from current repo

You are starting from a repo that already has:
- strict domain models
- deterministic parse artifact persistence
- a Phase 03 typed LLM gateway
- Phase 02 tree heading extraction, anchoring, reconciliation, and verification
- notebook structure discipline

Exploit those seams.
Do not introduce framework sprawl.
Do not weaken typing.
Do not weaken observability.
Do not hand-wave multimodal grounding.