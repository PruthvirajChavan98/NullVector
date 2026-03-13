Status note:
- implemented through Prompt 6 on 2026-03-11
- additive tree-pipeline contracts now include TOC detection/reconciliation, LLM verification assists,
  bottom-up summarization, strategy orchestration, and large-node decomposition
- final pipeline order now runs decomposition before optional final summarization

Act as a principal engineer working inside the existing StrataForge architecture. Implement Prompt 1 only. Do not invent new abstractions beyond what this repository already uses.

Repository constraints you must respect:

- Public typed models live in `src/strataforge/domain/models.py`.
- Public exports must be wired through:
  - `src/strataforge/domain/__init__.py`
  - `src/strataforge/__init__.py`
- Phase 02 page substrate is `PageArtifacts` in `src/strataforge/tree/headings.py`.
- Repeated header/footer detection already exists as:
  - `find_repeated_header_footer_lines(...)` in `src/strataforge/tree/headings.py`
- The LLM gateway contract is NOT `generate_structured`.
  Use the existing typed gateway contract only:
  - `StructuredLLMGateway.invoke(GatewayRequest[T])`
  - prompt builders belong under `src/strataforge/llm/prompts/`
  - structured response models should extend `StrataModel`
  - auditability must flow through the existing gateway automatically
- No new external dependencies.
- Use stdlib `re` only for deterministic pattern matching.
- Maintain strict Pydantic typing and frozen model behavior.
- Do not break existing Phase 02 behavior when no gateway is provided.

Objective

Implement deterministic-first TOC detection over persisted parse artifacts, with optional typed LLM fallback for ambiguous pages only.

Files to add or modify

1. Add new domain contracts in `src/strataforge/domain/models.py`
2. Export new contracts from:
   - `src/strataforge/domain/__init__.py`
   - `src/strataforge/__init__.py`
3. Add new prompt builder module:
   - `src/strataforge/llm/prompts/toc.py`
4. Update `src/strataforge/llm/prompts/__init__.py`
5. Add TOC detector implementation:
   - `src/strataforge/tree/toc.py`
6. Add tests and fixtures under the existing pytest layout

New domain contracts to add

All new models must extend `StrataModel`. Any new enums must extend `StrEnum`.

Add:

1. `TocDetectionMethod(StrEnum)`
   Values:
   - `DETERMINISTIC = "deterministic"`
   - `HYBRID = "hybrid"`
   - `LLM_ONLY = "llm_only"`

2. `TocPageScore`
   Fields:
   - `page_index: NonNegativeInt`
   - `pattern_match_count: NonNegativeInt`
   - `leader_dot_density: float = 0.0`
   - `numbering_density: float = 0.0`
   - `font_uniformity_signal: float = 0.0`
   - `consecutive_page_bonus: float = 0.0`
   - `repeated_header_penalty: float = 0.0`
   - `final_score: float`
   - `classified_as_toc: bool = False`
   - `classification_reason: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)`

   Validation:
   - all density/signal fields except penalty must be between 0 and 1
   - penalty must be between 0 and 1
   - final_score must be between 0 and 1

3. `TocDetectionResponse`
   Fields:
   - `is_toc: bool`
   - `confidence: float`
   - `reasoning: NonEmptyStr`

   Validation:
   - confidence between 0 and 1

4. `TocDetectionResult`
   Fields:
   - `toc_page_indices: tuple[NonNegativeInt, ...] = ()`
   - `toc_content: str | None = None`
   - `detection_method: TocDetectionMethod`
   - `page_scores: tuple[TocPageScore, ...] = Field(default_factory=tuple)`
   - `has_page_numbers: bool = False`

5. Extend `TreeBuildManifest` additively with:
   - `toc_detection_path: NonEmptyStr | None = None`

Do not add any required manifest fields without defaults.

Prompt builder

Create `src/strataforge/llm/prompts/toc.py` with:

1. `build_toc_detection_messages(*, page_text: str) -> tuple[LLMMessage, ...]`
2. Use the existing typed prompt style already present in `repair.py`, `summarization.py`, `verification.py`
3. The prompt must include only the page text, not system-level repository context, not parse metadata, not cross-page state
4. The model must be instructed to decide whether the provided page text is a table of contents page and return the typed schema only

Update `src/strataforge/llm/prompts/__init__.py` exports accordingly.

TOC detector implementation

Create `src/strataforge/tree/toc.py`.

Add a deterministic-first `TocDetector` class with constructor:

- `settings: TreeSettings`
- `gateway: StructuredLLMGateway | None = None`

Public method:

- `detect(self, *, pages: tuple[PageArtifacts, ...], artifact_root: str | None = None) -> TocDetectionResult`

Behavior

1. Deterministic first pass

For each page, compute TOC-likeness using only the page text plus optional rawdict if present.

Use explicit signals:

- lines matching TOC-like entry patterns, such as:
  - `<title><spaces><number>`
  - `<title><leader dots><number>`
  - numbered prefixes like `1`, `1.2`, `1.2.3`, `Chapter 3`, followed by title and trailing page number
- density of such matches on a page
- density of dotted leaders
- density of numbering prefixes
- rawdict-based font uniformity when rawdict is present
- consecutive-page continuation bonus if adjacent pages are also TOC-like
- repeated-header penalty using `find_repeated_header_footer_lines(...)`

Important:
- rawdict is optional and sparse in this repo; `font_uniformity_signal` must degrade to `0.0` when `rawdict is None`
- do not assume rawdict exists on every page
- do not use OCR or PDF parsing here; consume only provided `PageArtifacts`

2. Candidate page window

Restrict initial deterministic evaluation to the leading document region only. Add a small pure helper inside `toc.py` to determine the maximum number of pages to inspect.

Since `TreeSettings` currently has no TOC-specific fields, use a conservative fixed cap in this prompt:
- inspect first `min(len(pages), 20)` pages

Do not modify `TreeSettings` in this prompt just to add TOC thresholds. Keep prompt 1 low blast radius.

3. Scoring

Produce a `TocPageScore` per inspected page.

Use normalized `final_score` in `[0,1]`.

Implement internal thresholds as module constants in `toc.py`, for example:
- `DETERMINISTIC_HIGH_THRESHOLD = 0.70`
- `DETERMINISTIC_LOW_THRESHOLD = 0.45`

Classify:
- score >= high threshold => TOC without LLM
- score < low threshold => non-TOC without LLM
- low <= score < high => ambiguous, eligible for LLM only if gateway exists

4. Consecutive page logic

If a page is confidently TOC-like, allow subsequent adjacent pages with moderate scores to inherit a continuation bonus.
Stop extending the TOC page run once confidence drops clearly below the low threshold and no continuation evidence remains.

This should support multi-page TOCs while remaining deterministic.

5. LLM fallback

Only ambiguous pages may call the gateway, and only when `gateway is not None`.

Use:
- `build_toc_detection_messages(...)`
- `GatewayRequest[TocDetectionResponse]`
- response model `TocDetectionResponse`

Suggested operation name:
- `toc_detection`

Use transport-compatible structured output unless the provided gateway config overrides it elsewhere.

Do not create any new gateway wrapper.

6. Detection method

Set:
- `DETERMINISTIC` if no LLM call occurred
- `HYBRID` if deterministic + LLM were both used
- `LLM_ONLY` only if every positive TOC page in the result depended on LLM classification and no page crossed the deterministic high threshold

7. TOC content and page-number detection

Concatenate detected TOC page texts in page order into `toc_content`.

Set `has_page_numbers` by inspecting the resulting TOC content deterministically.
A simple robust rule is sufficient:
- detect at least two distinct TOC-like lines with trailing numeric page references

Do not use the gateway for `has_page_numbers`.

8. Artifact persistence

If `artifact_root` is provided, write:
- `<artifact_root>/toc-detection.json`

Keep the JSON writing style deterministic and consistent with existing tree artifacts.

Persist the full `TocDetectionResult`.

Implementation notes

Add pure helpers inside `toc.py` for:
- extracting TOC-like lines
- computing leader-dot density
- computing numbering density
- computing font uniformity from rawdict lines
- detecting page numbers from TOC content
- applying consecutive page bonus

Reuse line utilities from `tree/headings.py` where useful:
- `split_text_lines_with_offsets(...)`
- `extract_rawdict_lines(...)`
- `normalized_title_key(...)`
- `find_repeated_header_footer_lines(...)`

Do not move these helpers out of `headings.py` unless absolutely required.

Tests

Add tests that prove the architecture, not just output.

Required test coverage:

1. Deterministic TOC present fixture
Create a fixture with synthetic `PageArtifacts` representing:
- title page
- 2 TOC pages
- start of document body

The TOC pages should include realistic leader dots and page references.
Assert:
- TOC pages detected correctly
- `detection_method == deterministic`
- `has_page_numbers is True`
- no gateway calls occurred

2. Deterministic TOC absent fixture
Create a fixture with pages that resemble narrative front matter but not TOC.
Assert:
- no TOC pages detected
- `toc_content is None`
- `detection_method == deterministic`
- no gateway calls occurred

3. Ambiguous-page LLM fallback
Use `NoopProviderAdapter` with a scripted response and a real `GatewayService`.
Build a case where one page falls into the ambiguous threshold band.
Assert:
- gateway is called exactly for ambiguous pages
- result becomes `hybrid`
- returned `TocDetectionResponse` affects final classification
- audit-compatible gateway path is used, not any custom wrapper

4. Artifact persistence
Assert that `toc-detection.json` is written and round-trippable.

5. Rawdict optionality
Add a case where TOC detection works with `rawdict=None`.
Assert no exception and `font_uniformity_signal == 0.0`.

6. Repeated header/footer suppression
Add a page with repeated top-line boilerplate that might otherwise resemble TOC entries.
Assert the repeated-header penalty prevents false positive classification.

Integration

Do not yet wire this into the full `TreePipelineService.build()` flow unless it can be done with zero behavior change for existing tests.
If you do wire it in, it must be strictly additive and non-disruptive:
- TOC detection may run
- persisted path may be added to the manifest
- existing hierarchy behavior must remain unchanged in this prompt

Acceptance criteria

The implementation is complete only if all of the following are true:

- No invented gateway APIs
- No new external dependencies
- All new models are strictly typed and exported
- Deterministic detection works without gateway access
- Ambiguous-only LLM fallback works through `StructuredLLMGateway.invoke(...)`
- Artifact persistence is replayable
- Existing tests continue to pass
- New tests verify deterministic-first behavior and no unnecessary LLM calls

When finished, return:
1. the exact files changed
2. the exact tests added
3. a concise explanation of any assumptions made
4. any areas intentionally deferred to Prompt 2


---

Act as a principal engineer working inside the existing StrataForge architecture. Implement Prompt 2 only, assuming Prompt 1 has already been completed in this repository.

Do not invent new abstractions beyond what this repository already uses.

Repository constraints you must respect:

- Public typed models live in `src/strataforge/domain/models.py`
- Public exports must be wired through:
  - `src/strataforge/domain/__init__.py`
  - `src/strataforge/__init__.py`
- TOC detection contracts from Prompt 1 are the source of truth
- Heading anchoring already exists in:
  - `src/strataforge/tree/headings.py`
  - `anchor_title_on_page(...)`
- Current hierarchy trust logic lives in:
  - `src/strataforge/tree/hierarchy.py`
- The LLM gateway contract is the existing typed gateway:
  - `StructuredLLMGateway.invoke(GatewayRequest[T])`
- No new external dependencies
- Use stdlib `re` only
- Maintain strict Pydantic typing and frozen model behavior
- Preserve existing Phase 02 behavior when no TOC data exists and no gateway is provided

Objective

Implement deterministic TOC parsing and TOC-to-physical-page reconciliation, with optional typed LLM assistance only for ambiguous TOC parsing.

Files to add or modify

1. Add new domain contracts in `src/strataforge/domain/models.py`
2. Export new contracts from:
   - `src/strataforge/domain/__init__.py`
   - `src/strataforge/__init__.py`
3. Add new prompt builder module:
   - `src/strataforge/llm/prompts/toc_reconcile.py`
4. Update `src/strataforge/llm/prompts/__init__.py`
5. Add reconciliation implementation:
   - `src/strataforge/tree/toc_reconcile.py`
6. Update `src/strataforge/tree/hierarchy.py` additively
7. Add tests and fixtures under the existing pytest layout

New domain contracts to add

All new models must extend `StrataModel`. Any new enums must extend `StrEnum`.

Add:

1. `TocParseMethod(StrEnum)`
   Values:
   - `DETERMINISTIC = "deterministic"`
   - `LLM_ASSISTED = "llm_assisted"`

2. `TocParsedEntry`
   Fields:
   - `structure: str | None = None`
   - `title: NonEmptyStr`
   - `page_number: NonNegativeInt | None = None`

3. `TocParseResponse`
   Fields:
   - `entries: tuple[TocParsedEntry, ...]`

4. `TocReconciliationResult`
   Fields:
   - `parsed_entries: tuple[TocParsedEntry, ...] = Field(default_factory=tuple)`
   - `offset: int | None = None`
   - `offset_confidence: float = 0.0`
   - `reconciled_candidates: tuple[HeadingCandidate, ...] = Field(default_factory=tuple)`
   - `parse_method: TocParseMethod`

   Validation:
   - `offset_confidence` must be between 0 and 1

5. Extend `OutlineTrustMode` additively with:
   - `TOC_RECONCILED = "toc_reconciled"`

6. Extend `TreeBuildManifest` additively with:
   - `toc_reconciliation_path: NonEmptyStr | None = None`

Do not add required manifest fields without defaults.

Prompt builder

Create `src/strataforge/llm/prompts/toc_reconcile.py` with:

1. `build_toc_parse_messages(*, toc_text: str) -> tuple[LLMMessage, ...]`
2. It must request only structured parsing of the TOC text into:
   - structure
   - title
   - page_number
3. The prompt must include only the TOC text
4. It must not include repository context or pipeline state

Update `src/strataforge/llm/prompts/__init__.py` exports accordingly.

Reconciler implementation

Create `src/strataforge/tree/toc_reconcile.py`.

Add a `TocReconciler` class with constructor:

- `settings: TreeSettings`
- `gateway: StructuredLLMGateway | None = None`

Public method:

- `reconcile(
      self,
      *,
      document_id: str,
      pages: tuple[PageArtifacts, ...],
      toc_result: TocDetectionResult,
      artifact_root: str | None = None,
  ) -> TocReconciliationResult`

Behavior

1. Deterministic TOC parsing first

From `toc_result.toc_content`, parse entries using regex-first deterministic logic.

Handle common formats including at minimum:
- `1.2.3 Title ........ 45`
- `1 Title 45`
- `Chapter 3: Title 45`
- `Title    45`

A deterministic parse should extract:
- optional structure prefix
- title
- optional logical page number

If deterministic parsing produces a materially useful result, use it.
Do not route cleanly parseable TOCs through the gateway.

2. LLM-assisted parsing only when needed

Only if deterministic parsing is ambiguous or too sparse, and `gateway is not None`, call the gateway.

Use:
- `build_toc_parse_messages(...)`
- `GatewayRequest[TocParseResponse]`
- operation name: `toc_parse`

Use the existing typed gateway only.

3. Page offset calculation must be fully deterministic

For every parsed TOC entry with a logical page number:
- predict a candidate physical page from the logical page number plus an unknown offset
- anchor the entry title against real pages using `anchor_title_on_page(...)`
- collect `(logical_page, physical_page)` pairs
- compute the offset as the mode of `(physical_page - logical_page)`

Important:
- offset calculation must not use any LLM calls
- do not search all pages naively if a narrower window can be used
- remain deterministic

4. Offset confidence

Set `offset_confidence` as:
- agreeing_pairs / total_pairs_used

If there are no reliable anchor pairs:
- `offset = None`
- `offset_confidence = 0.0`
- `reconciled_candidates = ()`

5. Reconciled candidates

When `offset` is available:
- apply the offset to each parsed entry with a page number
- locate or anchor the title on the predicted physical page
- build `HeadingCandidate` objects for successfully anchored entries

Requirements for TOC-derived candidates:
- `source_kind = HeadingSourceKind.OUTLINE`
- `outline_level_hint` or `level_hint` should be inferred from structure depth where available
- `score_breakdown` must be explicit and deterministic, not fake-empty
- mark them as kept/high-confidence only when anchoring actually succeeded

6. Integration-ready hooks in hierarchy logic

Update `src/strataforge/tree/hierarchy.py` additively:

- `determine_outline_trust_mode(...)` must accept an optional parameter:
  - `toc_candidates: Sequence[HeadingCandidate] = ()`
- `reconcile_heading_candidates(...)` must accept an optional parameter:
  - `toc_candidates: Sequence[HeadingCandidate] = ()`

Behavior:
- When TOC-derived candidates are absent, preserve current behavior exactly
- When TOC-derived candidates are present and well anchored, `OutlineTrustMode.TOC_RECONCILED` may be selected
- Do not break existing call sites by making the new parameter optional with a default

Important:
- Do not yet rewrite the full pipeline orchestration around TOC.
- This prompt prepares the integration surface. Full strategy orchestration belongs to Prompt 5.

7. Artifact persistence

If `artifact_root` is provided, write:
- `<artifact_root>/toc-reconciliation.json`

Persist the full `TocReconciliationResult`.

Implementation notes

Add pure helpers inside `toc_reconcile.py` for:
- deterministic TOC line parsing
- structure depth inference
- anchor pair collection
- mode offset calculation
- TOC-entry-to-candidate conversion

Reuse existing helpers where possible:
- `anchor_title_on_page(...)`
- `numbering_depth(...)`
- `normalized_title_key(...)`

Do not introduce a new PDF-reading layer.

Tests

Required coverage:

1. Deterministic TOC parsing
A fixture with TOC text containing numbered entries and logical page numbers.
Assert:
- entries parsed correctly
- parse method is deterministic
- no gateway calls occur

2. Offset reconciliation with +2 offset
Create a fixture where logical TOC pages are offset by +2 relative to physical page indices.
Assert:
- `offset == 2`
- `offset_confidence > 0`
- reconciled candidates point to the correct physical pages

3. LLM-assisted parsing fallback
Use `NoopProviderAdapter` with a scripted `TocParseResponse`.
Create a TOC text format that deterministic regex intentionally cannot parse well.
Assert:
- gateway invoked only for parsing
- offset computation still remains deterministic
- parse method is `llm_assisted`

4. No offset case
Create a case where parsed entries exist but cannot be anchored reliably.
Assert:
- `offset is None`
- `offset_confidence == 0.0`
- reconciled candidates empty

5. Hierarchy hook backward compatibility
Call the updated hierarchy functions without `toc_candidates`.
Assert existing behavior remains unchanged.

Integration guardrail

Do not make TOC reconciliation mandatory in the main pipeline in this prompt.
Any build-path wiring must be optional and strictly additive.
Existing Phase 02 tests must continue to pass unmodified.

Acceptance criteria

The implementation is complete only if all of the following are true:

- Deterministic TOC parsing handles the common case
- LLM assistance is used only for ambiguous parsing
- Offset calculation uses no LLM calls
- TOC-derived heading candidates are anchored, typed, and deterministic
- `OutlineTrustMode.TOC_RECONCILED` is added without breaking old behavior
- Reconciliation results persist as replayable artifacts
- Existing tests continue to pass
- New tests prove offset computation and backward compatibility

When finished, return:
1. the exact files changed
2. the exact tests added
3. assumptions made
4. anything intentionally deferred to Prompt 5


---

Act as a principal engineer working inside the existing StrataForge architecture. Implement Prompt 3 only, assuming Prompts 1 and 2 may or may not already exist.

Do not invent new abstractions beyond what this repository already uses.

Repository constraints you must respect:

- Verification logic currently lives in `src/strataforge/tree/verify.py`
- Verification prompt artifacts already exist in:
  - `src/strataforge/llm/prompts/verification.py`
- The structured response model already exists:
  - `VerificationPromptResponse`
- The gateway contract is the existing typed gateway:
  - `StructuredLLMGateway.invoke(GatewayRequest[T])`
- Gateway auditing already exists and must remain the only audit system for provider calls
- No new external dependencies
- Preserve existing verification behavior exactly when no assistant is provided

Objective

Add an opt-in LLM verification assistant for nodes that fail deterministic title verification, while validating all returned evidence against the source text deterministically.

Files to add or modify

1. Add any new domain contracts needed in `src/strataforge/domain/models.py`
2. Export them from:
   - `src/strataforge/domain/__init__.py`
   - `src/strataforge/__init__.py`
3. Update `src/strataforge/llm/prompts/verification.py` only as needed
4. Add or extend verification assistant logic in:
   - `src/strataforge/tree/verify.py`
5. Add tests under the existing pytest layout

New domain changes

1. Extend `TitleMatchTier` additively with:
   - `LLM_VERIFIED = "llm_verified"`

2. Add a persistable assist record model:
   - `LLMVerificationAssistRecord`
   Fields:
   - `node_id: NonEmptyStr`
   - `title: NonEmptyStr`
   - `page_index: NonNegativeInt`
   - `llm_verdict: NonEmptyStr`
   - `llm_rationale: NonEmptyStr`
   - `supporting_quotes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)`
   - `grounded_quotes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)`
   - `ungrounded_quotes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)`
   - `accepted: bool = False`

3. Extend `TreeBuildManifest` additively with:
   - `llm_verification_assists_path: NonEmptyStr | None = None`

Do not add required manifest fields without defaults.

Prompt builder

Use the existing `VerificationPromptResponse` model.

Update `build_verification_messages(...)` only if needed, but keep it backward compatible.
The prompt must be grounded and bounded.

The prompt content must include:
- the node title
- the first 3 lines of the claimed page, or a bounded excerpt derived from them
- the expected page span
- an explicit instruction equivalent to:
  - `Does the section titled "{title}" begin on this page? Only use the provided text. Do not infer from outside knowledge.`

Do not add free-form system context about the whole pipeline.

Verification assistant implementation

In `src/strataforge/tree/verify.py`, add an `LLMVerificationAssistant` class.

Constructor:
- `gateway: StructuredLLMGateway`
- `artifact_root: str | None = None`

Public method:
- `assist(
      self,
      *,
      node: HierarchyNode,
      page: PageArtifacts,
      settings: TreeSettings,
  ) -> tuple[TitleMatchTier, LLMVerificationAssistRecord]`

Behavior

1. Selective invocation only

Only invoke the assistant for nodes whose deterministic result is `TitleMatchTier.NONE`.

Do not call the gateway for:
- exact normalized matches
- casefold/punctuation matches
- token containment matches
- edit-distance matches

2. Grounded prompt input

Use only bounded page-local text.
Derive the excerpt from page lines using existing helpers in `tree/headings.py`.

The excerpt must remain small and deterministic.
Do not send full-document context.

3. Structured gateway call

Use:
- `GatewayRequest[VerificationPromptResponse]`
- existing builder in `llm/prompts/verification.py`
- operation name: `verify_heading_title`

4. Evidence grounding validation

After the gateway returns:
- for each quote in `supporting_quotes`, verify that the quote exists verbatim in `page.text`
- quotes that do not exist must be classified as ungrounded
- only accept the LLM assist if:
  - the verdict is positive in a clearly defined deterministic way, and
  - at least one supporting quote is grounded

Define a narrow deterministic positive-verdict rule inside `verify.py`.
Do not rely on fuzzy interpretation of the LLM verdict string.

5. Returned match tier

If the assist is accepted:
- return `TitleMatchTier.LLM_VERIFIED`

Otherwise:
- keep `TitleMatchTier.NONE`

6. Artifact persistence

If `artifact_root` is provided, persist all assist records to:
- `<artifact_root>/verify/llm-assists.json`

This persistence must be deterministic and replayable.

7. verify_hierarchy integration

Update `verify_hierarchy(...)` additively with:
- `verification_assistant: LLMVerificationAssistant | None = None`

Behavior:
- existing behavior must remain identical when assistant is `None`
- when assistant is provided, nodes that fail deterministic verification may get a second chance through the LLM path
- if accepted, the node should pass verification and carry `verification_match_tier = llm_verified`

Important:
- do not change the pass/fail outcome for nodes that already pass deterministic verification
- do not bypass parent-span or level-jump validation

Implementation notes

- Keep this prompt sync-first, matching the current repo
- Do not introduce async-only flows into the tree pipeline
- Reuse:
  - `split_text_lines_with_offsets(...)`
  - `determine_title_match_tier(...)`
- Keep LLM verdict parsing deterministic and explicit

Tests

Required coverage:

1. No assistant path backward compatibility
Run current verification behavior with `verification_assistant=None`.
Assert output remains unchanged.

2. Assistant invoked only on NONE failures
Create nodes that produce:
- exact match
- token containment
- none
Assert the gateway is called only for the NONE case.

3. Accepted grounded assist
Use `NoopProviderAdapter` and `GatewayService`.
Return a positive verdict and supporting quotes that actually exist in page text.
Assert:
- node becomes `llm_verified`
- verification passes
- assist record is accepted

4. Rejected due to ungrounded quotes
Return a positive verdict with quotes not present in the page.
Assert:
- assist is rejected
- match tier remains none
- node still fails

5. Rejected negative verdict
Return a negative verdict even with a plausible quote.
Assert:
- node remains failed
- assist record is persisted with `accepted=False`

6. Artifact persistence
Assert `verify/llm-assists.json` is written and round-trippable.

Acceptance criteria

The implementation is complete only if all of the following are true:

- `TitleMatchTier.LLM_VERIFIED` is added additively
- LLM verification is opt-in only
- Gateway is called only for deterministic failures
- Supporting quotes are validated against source text deterministically
- Existing verification behavior is unchanged when assistant is not provided
- Assist records are persisted replayably
- Existing tests continue to pass

When finished, return:
1. the exact files changed
2. the exact tests added
3. assumptions made
4. any verification edge cases intentionally deferred


---


Act as a principal engineer working inside the existing StrataForge architecture. Implement Prompt 4 only.

Do not invent abstractions that fight the current sync-first repository design.

Repository constraints you must respect:

- The tree pipeline is currently sync-first
- The gateway contract is sync:
  - `StructuredLLMGateway.invoke(GatewayRequest[T])`
- Existing summarization prompt artifacts live in:
  - `src/strataforge/llm/prompts/summarization.py`
- `NodeCard` already contains:
  - `summary: str | None`
  - `keywords: tuple[...]`
- No new external dependencies
- Preserve existing tree-build behavior exactly when summarization is disabled

Important correction to the original idea:
- Do not force `asyncio.gather` into a sync-first pipeline just because the source prompt said so.
- Use a deterministic sync orchestration model.
- If you want per-level concurrency, use a small `ThreadPoolExecutor` boundary while preserving deterministic result ordering.

Objective

Implement bottom-up hierarchical summarization for committed nodes only, where parent summaries are derived from parent prefix text plus child summaries, not by re-sending the full subtree text.

Files to add or modify

1. Add any new domain contracts in `src/strataforge/domain/models.py`
2. Export them from:
   - `src/strataforge/domain/__init__.py`
   - `src/strataforge/__init__.py`
3. Update or extend:
   - `src/strataforge/llm/prompts/summarization.py`
4. Add summarization implementation:
   - `src/strataforge/tree/summarize.py`
5. Update:
   - `src/strataforge/tree/service.py`
6. Add tests under the existing pytest layout

New domain contracts

Add:

1. `NodeSummaryMethod(StrEnum)`
   Values:
   - `PASSTHROUGH = "passthrough"`
   - `LLM_LEAF = "llm_leaf"`
   - `LLM_PARENT = "llm_parent"`

2. `NodeSummary`
   Fields:
   - `node_id: NonEmptyStr`
   - `summary: NonEmptyStr`
   - `keywords: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)`
   - `summary_method: NodeSummaryMethod`
   - `token_count: NonNegativeInt`

3. Extend `NodeCard` additively with:
   - `summary_method: NodeSummaryMethod | None = None`
   - `summary_token_count: NonNegativeInt | None = None`

4. Extend `TreeBuildRequest` additively with:
   - `summarize: bool = False`

5. Extend `TreeBuildManifest` additively with:
   - `node_summaries_path: NonEmptyStr | None = None`

Do not add required fields without defaults.

Prompt artifacts

Use the existing `SummarizationPromptResponse` model.

You may extend `build_summarization_messages(...)` if needed, but keep it backward compatible.

You must support two prompt shapes:

1. Leaf summarization input:
- node title
- bounded excerpts from the node’s own text

2. Parent summarization input:
- node title
- parent prefix text only
- child title + child summary pairs

The prompt must explicitly instruct the model not to invent information.

Summarizer implementation

Create `src/strataforge/tree/summarize.py`.

Add a `NodeSummarizer` class with constructor:

- `gateway: StructuredLLMGateway`
- `max_workers: int = 4`

Public method:

- `summarize(
      self,
      *,
      nodes: tuple[HierarchyNode, ...],
      pages: tuple[PageArtifacts, ...],
      artifact_root: str | None = None,
  ) -> tuple[tuple[HierarchyNode, ...], tuple[NodeCard, ...], tuple[NodeSummary, ...]]`

Behavior

1. Bottom-up traversal

Summaries must be produced bottom-up:
- summarize leaf nodes first
- then summarize parents using:
  - the parent’s own prefix text
  - already-computed child summaries

Do not summarize parents from full subtree text.

2. Prefix-text extraction

You must deterministically compute a parent node’s own prefix text:
- text from the node heading anchor forward
- limited to the node’s own page span
- excluding the text owned by its first child and descendants

You may add small private helpers for this inside `summarize.py`.

3. Leaf passthrough rule

For leaf nodes, use a deterministic token estimator such as:
- `max(1, int(len(text.split()) * 1.3))`

If estimated tokens are below a module constant threshold, e.g. `200`, then:
- set summary to the raw text directly
- `summary_method = passthrough`

4. LLM leaf summarization

For leaf nodes above threshold:
- call the gateway using `SummarizationPromptResponse`
- operation name: `summarize_leaf_node`

5. LLM parent summarization

For non-leaf nodes:
- build the prompt from parent prefix text plus child summaries
- call the gateway using `SummarizationPromptResponse`
- operation name: `summarize_parent_node`

6. Concurrency within depth levels

Because the repo is sync-first, implement bounded per-level concurrency using `ThreadPoolExecutor`.
Requirements:
- levels must still be processed bottom-up sequentially
- results must be written back in deterministic node order
- no race-dependent output ordering

7. Pipeline integration

Update `TreePipelineService.build(...)` additively:
- when `request.summarize is False`, behavior must be unchanged
- summarization runs only after verification and only on committed nodes
- update `NodeCard.summary`, `NodeCard.keywords`, `NodeCard.summary_method`, and `NodeCard.summary_token_count`
- if summarization is requested and no gateway is configured, raise `TreePipelineError`

Important:
- do not summarize failed or discarded nodes
- do not change node IDs or hierarchy structure

8. Artifact persistence

If summarization runs, persist:
- `<tree_root>/summaries/node-summaries.json`

The artifact should map cleanly to `NodeSummary` data and be replayable.

Implementation notes

- Keep token estimation deterministic
- Do not add `tiktoken`
- Keep summarization prompt inputs bounded and stable
- Avoid sending full subtree text for parents

Tests

Required coverage:

1. Leaf passthrough
Create a short leaf node below threshold.
Assert:
- no gateway call
- summary equals raw text
- method is `passthrough`

2. Long leaf summarization
Use `NoopProviderAdapter` and `GatewayService`.
Assert:
- gateway called
- method is `llm_leaf`
- summary and keywords are written to node cards

3. Parent summarization uses child summaries
Construct a small 2-level hierarchy.
Assert:
- parent prompt uses child summaries and parent prefix text
- full subtree raw text is not required to build parent summaries
- method is `llm_parent`

4. Bottom-up ordering
Assert children are summarized before parents.

5. Build-path integration
Run `TreePipelineService.build(...)` with `summarize=False` and `summarize=True`.
Assert:
- unchanged behavior when disabled
- summaries present when enabled

6. Missing gateway error
If `summarize=True` and no gateway is supplied, assert `TreePipelineError`.

7. Artifact persistence
Assert `summaries/node-summaries.json` exists and is round-trippable.

Acceptance criteria

The implementation is complete only if all of the following are true:

- Bottom-up summarization is implemented
- Parent summaries use parent prefix text plus child summaries only
- The sync-first pipeline remains sync-first
- Per-level concurrency, if implemented, is deterministic
- Existing build behavior is unchanged when summarization is disabled
- Summaries persist as replayable artifacts
- Existing tests continue to pass

When finished, return:
1. the exact files changed
2. the exact tests added
3. assumptions made
4. any summarization tradeoffs intentionally chosen


---


Act as a principal engineer working inside the existing StrataForge architecture. Implement Prompt 5 only, assuming Prompts 1 to 4 may exist.

Do not replace working logic with a theoretical framework. Build a typed orchestration layer around the current pipeline behavior and preserve backward compatibility.

Repository constraints you must respect:

- Current build orchestration lives in `src/strataforge/tree/service.py`
- Current trust-mode logic lives in `src/strataforge/tree/hierarchy.py`
- Existing tree pipeline already has:
  - heading extraction
  - hierarchy assembly
  - repair
  - verification
- TOC detection/reconciliation and LLM verification may now exist from prior prompts
- No new external dependencies
- Existing Phase 02 tests must continue to pass unmodified

Objective

Introduce a typed hierarchy strategy selection and fallback cascade system without changing the default output path for current fixtures.

Files to add or modify

1. Add new domain contracts in `src/strataforge/domain/models.py`
2. Export them from:
   - `src/strataforge/domain/__init__.py`
   - `src/strataforge/__init__.py`
3. Add new orchestration module:
   - `src/strataforge/tree/strategy.py`
4. Update:
   - `src/strataforge/tree/service.py`
5. Add tests under the existing pytest layout

New domain contracts

Add:

1. `HierarchyStrategy(StrEnum)`
   Values:
   - `OUTLINE_WITH_TOC_RECONCILIATION = "outline_with_toc_reconciliation"`
   - `OUTLINE_ONLY = "outline_only"`
   - `TOC_DERIVED = "toc_derived"`
   - `INFERRED_WITH_LLM_ASSIST = "inferred_with_llm_assist"`
   - `INFERRED_DETERMINISTIC = "inferred_deterministic"`

2. `StrategyRationale`
   Fields:
   - `reasons: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)`
   - `outline_available: bool`
   - `toc_available: bool`
   - `gateway_available: bool`

3. `StrategyExecutionReport`
   Fields:
   - `attempted_strategies: tuple[HierarchyStrategy, ...]`
   - `selected_strategy: HierarchyStrategy`
   - `rationale: StrategyRationale`
   - `cascade_depth: NonNegativeInt`
   - `accuracy_at_each_level: tuple[float, ...] = Field(default_factory=tuple)`

4. Extend `TreeSettings` additively with:
   - `strategy_accuracy_threshold: PositiveFloat = 0.60`
   - `max_strategy_cascade_depth: PositiveInt = 2`

5. Extend `TreeBuildManifest` additively with:
   - `strategy_execution_report_path: NonEmptyStr | None = None`

Do not add required fields without defaults.

Strategy module

Create `src/strataforge/tree/strategy.py`.

Implement:

1. `select_hierarchy_strategy(...) -> tuple[HierarchyStrategy, StrategyRationale]`
2. `execute_hierarchy_strategy(...) -> ...`
3. Any small internal helpers needed

Inputs should include:
- selected outline source/report data
- outline candidates
- inferred candidates
- optional TOC results/candidates
- optional verification assistant
- whether a gateway is available
- settings

Behavior

1. Strategy selection must be pure and deterministic

Given the same inputs and settings, the chosen strategy must be identical.

2. Default behavior must preserve existing Phase 02 semantics

For existing fixtures with no TOC data and no gateway:
- the first selected strategy must reduce to current behavior
- current outputs must remain unchanged

In practice:
- if current trust logic would choose outline-primary or hybrid, the default strategy should map to `OUTLINE_ONLY`
- if current trust logic would choose inferred-primary, the default strategy should map to `INFERRED_DETERMINISTIC`

3. Strategy meanings

- `OUTLINE_WITH_TOC_RECONCILIATION`
  Use outline candidates plus TOC-reconciled candidates if available
- `OUTLINE_ONLY`
  Use the current outline/inferred trust path without TOC or LLM verification changes
- `TOC_DERIVED`
  Use TOC-derived candidates when outline is absent or untrustworthy and TOC exists
- `INFERRED_WITH_LLM_ASSIST`
  Use inferred candidates plus the optional verification assistant from Prompt 3
- `INFERRED_DETERMINISTIC`
  Use inferred candidates with no LLM assistance

4. Accuracy check and cascade

After each strategy attempt, compute a lightweight accuracy score:
- fraction of committed nodes whose verification tier is better than `none`

If accuracy is below `settings.strategy_accuracy_threshold`, and another lower-priority strategy is available:
- cascade to the next strategy
- cap attempts by `settings.max_strategy_cascade_depth`

5. Auditable attempt artifacts

Each strategy attempt must write a full attempt subtree under something like:
- `<tree_root>/strategy/attempts/<index>-<strategy.value>/...`

Each attempt should contain its own:
- selected candidates
- hierarchy outputs
- verification outputs
- any strategy-local notes needed for auditability

6. Final selected output

The main manifest paths should still point to the final selected attempt’s committed hierarchy/node cards/report outputs.
The strategy execution report should point to the overall strategy decision artifact.

7. service.py integration

Replace the hard-coded call chain in `TreePipelineService.build(...)` with the strategy selector/executor layer.

Important:
- keep the underlying deterministic builders and verifiers intact
- do not duplicate core logic unnecessarily
- the strategy layer should orchestrate existing components, not rewrite them

Implementation notes

- Keep strategy ordering explicit and deterministic
- Avoid introducing recursion into strategy execution
- Preserve repair-engine handling
- Preserve manifest idempotency behavior

Tests

Required coverage:

1. Backward-compatible default path
For an existing fixture with no TOC and no gateway:
- assert selected strategy matches the current effective behavior
- assert final outputs are unchanged

2. TOC-derived availability
When TOC-reconciled candidates exist and outline is weak:
- assert a TOC-aware strategy can be selected

3. Inferred with LLM assist
When gateway is available and deterministic inferred verification underperforms:
- assert `INFERRED_WITH_LLM_ASSIST` may be attempted

4. Cascade behavior
Construct a case where first strategy underperforms and second strategy succeeds.
Assert:
- attempted strategies length > 1
- cascade depth increments correctly
- final selected strategy is the later one

5. No-gateway behavior
When no gateway exists:
- assert LLM-dependent strategies are not attempted
- cascade still completes deterministically

6. Attempt artifact persistence
Assert strategy attempt artifacts and execution report are written.

Acceptance criteria

The implementation is complete only if all of the following are true:

- Strategy selection is typed and deterministic
- Cascade behavior is typed and bounded
- Existing Phase 02 fixtures retain their current code path and outputs by default
- No-gateway mode still works fully
- Attempt artifacts are auditable
- Final manifest points at the selected attempt outputs
- Existing tests continue to pass

When finished, return:
1. the exact files changed
2. the exact tests added
3. assumptions made
4. how default backward compatibility was preserved


---

Act as a principal engineer working inside the existing StrataForge architecture. Implement Prompt 6 only, assuming Prompts 1 to 5 may exist.

This prompt must be adapted to the real repository shape, not the conceptual one.

Repository constraints you must respect:

- The committed hierarchy is a flat tuple of `HierarchyNode` objects with:
  - `parent_id`
  - `path`
  - `level`
  - `page_span`
  - `heading_anchor`
- There is no nested in-memory tree object in the current pipeline
- Heading extraction already exists in:
  - `src/strataforge/tree/headings.py`
- Verification currently assumes top-of-page heading checks, so decomposition must account for in-page subsection headings carefully
- The gateway is sync-first:
  - `StructuredLLMGateway.invoke(GatewayRequest[T])`
- No new external dependencies

Critical implementation note

The original source prompt assumes decomposition can simply re-use the current verification logic unchanged. That is not true in this repo, because decomposed child headings may begin mid-page and the current verifier looks only at the top few lines of a page.

You must therefore make the minimum additive verification change needed to support decomposed mid-page children without breaking existing verification behavior for ordinary top-of-page headings.

Objective

Implement bounded recursive decomposition of very large committed leaf nodes, using deterministic heading extraction first and optional LLM assistance only when deterministic subdivision fails.

Files to add or modify

1. Add new domain contracts in `src/strataforge/domain/models.py`
2. Export them from:
   - `src/strataforge/domain/__init__.py`
   - `src/strataforge/__init__.py`
3. Add new prompt builder module:
   - `src/strataforge/llm/prompts/decomposition.py`
4. Update `src/strataforge/llm/prompts/__init__.py`
5. Add decomposition implementation:
   - `src/strataforge/tree/decompose.py`
6. Update verification additively in:
   - `src/strataforge/tree/verify.py`
7. Update:
   - `src/strataforge/tree/service.py`
8. Add tests under the existing pytest layout

New domain contracts

Add:

1. `DecompositionMethod(StrEnum)`
   Values:
   - `DETERMINISTIC = "deterministic"`
   - `LLM_ASSISTED = "llm_assisted"`
   - `NONE = "none"`

2. `DecompositionBoundary`
   Fields:
   - `title: NonEmptyStr`
   - `page_index: NonNegativeInt`
   - `level_hint: PositiveInt | None = None`

3. `DecompositionPromptResponse`
   Fields:
   - `entries: tuple[DecompositionBoundary, ...] = Field(default_factory=tuple)`

4. `DecompositionReport`
   Fields:
   - `decomposed_node_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)`
   - `new_child_count: NonNegativeInt = 0`
   - `decomposition_method: DecompositionMethod`
   - `depth: NonNegativeInt = 0`

5. Extend `TreeSettings` additively with:
   - `max_pages_per_leaf_node: PositiveInt = 10`
   - `max_tokens_per_leaf_node: PositiveInt = 20000`
   - `max_decomposition_depth: PositiveInt = 2`

6. Extend `TreeBuildManifest` additively with:
   - `decomposition_report_path: NonEmptyStr | None = None`

Do not add required fields without defaults.

Prompt builder

Create `src/strataforge/llm/prompts/decomposition.py` with:

1. `build_decomposition_messages(
      *,
      node_title: str,
      page_text: str,
   ) -> tuple[LLMMessage, ...]`

Prompt requirements:
- include the current node title
- include bounded page text with `<page_N>` markers
- instruct the model to identify subsection boundaries only if visibly supported by the text
- require the structured schema only

Update `llm/prompts/__init__.py` accordingly.

Decomposer implementation

Create `src/strataforge/tree/decompose.py`.

Add a `NodeDecomposer` class with constructor:

- `settings: TreeSettings`
- `gateway: StructuredLLMGateway | None = None`

Public method:

- `decompose(
      self,
      *,
      nodes: tuple[HierarchyNode, ...],
      pages: tuple[PageArtifacts, ...],
      tree_run_id: str,
      artifact_root: str | None = None,
  ) -> tuple[tuple[HierarchyNode, ...], DecompositionReport]`

Behavior

1. Identify candidate leaf nodes

A node is a decomposition candidate if:
- it is currently a committed leaf node
- page span length exceeds `settings.max_pages_per_leaf_node`
  OR
- estimated token count exceeds `settings.max_tokens_per_leaf_node`

Use a deterministic token estimator.
Do not add `tiktoken`.

2. Deterministic decomposition first

For the pages inside the candidate node’s span:
- rerun heading extraction on only that page subset
- use a copied settings object with a lower keep threshold to increase sensitivity
- keep the change local to decomposition; do not globally lower tree thresholds

If deterministic extraction yields at least 2 credible sub-headings:
- use that result
- do not call the gateway

3. LLM decomposition fallback

Only when deterministic decomposition yields fewer than 2 usable sub-headings, and `gateway is not None`, call the gateway.

Use:
- `GatewayRequest[DecompositionPromptResponse]`
- `build_decomposition_messages(...)`
- operation name: `decompose_large_node`

4. Convert boundaries into child hierarchy nodes

New decomposition children must become normal `HierarchyNode` entries:
- `parent_id` = original node id
- `path` extends the parent path
- `level` = parent level + 1 unless a safe deterministic hint says otherwise
- `page_span` derived from sibling ordering within the parent span
- `heading_anchor` anchored from the actual page text

Important:
- the committed hierarchy remains a flat tuple of nodes
- children must be inserted in stable document order
- node IDs must be generated using the existing node ID scheme

5. Original parent span truncation

After adding decomposition children:
- the original parent node’s `page_span` should be truncated to the prefix before its first child
- do not let parent and child page coverage become nonsensical
- preserve deterministic span construction

6. Recursive depth limit

Support recursive decomposition, but cap it at:
- `settings.max_decomposition_depth`

7. Minimal additive verification change

Update `verify.py` so decomposed children can be verified without breaking existing behavior.

Required approach:
- keep current top-of-page verification behavior for ordinary nodes
- add a bounded fallback that can verify against lines near the node’s own heading anchor when the heading is clearly mid-page

This fallback must remain deterministic and local.
Do not replace the current verification model wholesale.

8. Pipeline integration

Update `TreePipelineService.build(...)` additively so that decomposition runs only after:
- hierarchy build
- repair
- verification
- committed-node selection

Then:
- decompose the committed leaf nodes
- re-run verification on the decomposed hierarchy
- re-project node cards from the final committed hierarchy

Important:
- if decomposition is not needed, pipeline behavior must remain unchanged
- if decomposition occurs, final artifacts must reflect the decomposed committed hierarchy

9. Artifact persistence

Persist:
- `<tree_root>/decomposition/report.json`

If helpful for auditability, also persist a decomposition-local hierarchy artifact tree.

Implementation notes

- Reuse existing heading extraction and hierarchy building primitives where practical
- Avoid rewriting the whole pipeline for this prompt
- Keep decomposition deterministic-first
- LLM usage must remain bounded and optional

Tests

Required coverage:

1. Deterministic large-node decomposition
Create a fixture with a large committed leaf node spanning multiple pages and containing 3 visible sub-headings.
Assert:
- deterministic decomposition fires
- at least 3 child nodes are created
- no gateway call occurs

2. LLM fallback decomposition
Create a case with a large node whose subsection boundaries are too weak for deterministic extraction.
Use `NoopProviderAdapter` and `GatewayService`.
Assert:
- gateway is called
- method is `llm_assisted`

3. Depth limit
Create nested large sections.
Assert decomposition stops at `max_decomposition_depth`.

4. Parent span truncation
Assert the original parent span is reduced to prefix coverage before the first child.

5. Mid-page verification support
Create a decomposed child whose heading begins mid-page.
Assert the additive verification fallback can validate it without breaking ordinary top-of-page cases.

6. Build-path integration
Run the full build path on a decomposition fixture.
Assert final committed hierarchy includes decomposed children and node cards are updated.

7. Artifact persistence
Assert decomposition report exists and is round-trippable.

Acceptance criteria

The implementation is complete only if all of the following are true:

- Large leaf-node detection is deterministic
- Deterministic decomposition is attempted before any LLM call
- LLM decomposition is bounded and optional
- Decomposed children are represented as normal flat `HierarchyNode` entries
- Verification is minimally extended to support mid-page headings
- Existing non-decomposition behavior remains unchanged
- Decomposition artifacts are auditable
- Existing tests continue to pass

When finished, return:
1. the exact files changed
2. the exact tests added
3. assumptions made
4. the precise verification change required for mid-page headings

---

Execute these prompts in this exact order:

1. Prompt 1 — TOC Detection and Extraction from Parse Artifacts
2. Prompt 2 — TOC-to-Hierarchy Reconciliation with Page Offset Calculation
3. Prompt 3 — LLM-Backed Verification with Grounded Evidence
4. Prompt 4 — Hierarchical Node Summarization with Bottom-Up Aggregation
5. Prompt 5 — Fallback Cascade for Hierarchy Construction
6. Prompt 6 — Large Node Recursive Decomposition

Non-negotiable constraints across all prompts:

- Use the real StrataForge repo APIs, not imaginary ones
- Use `StructuredLLMGateway.invoke(GatewayRequest[T])` for all LLM work
- All new models extend `StrataModel`
- All new enums extend `StrEnum`
- No new external dependencies
- Preserve existing Phase 02 behavior unless the new feature is explicitly enabled or relevant artifacts exist
- Prefer additive manifest changes with optional fields only
- Every new artifact written must be replayable and deterministic
- Existing tests must continue to pass after each prompt, not just at the end

For each prompt:
- implement only that prompt’s scope
- run the relevant tests
- return exact files changed, exact tests added, assumptions, and any deferred items
