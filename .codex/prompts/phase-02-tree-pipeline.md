# Codex Prompt — Phase 02 Tree Pipeline

You are working on NullVector.

Mission:
Implement deterministic hierarchy synthesis, grounding, and verification on top of Phase 01 parser artifacts.

Primary input artifacts:
- manifest.json
- outline/selected.json
- ledger/page-ledger.jsonl
- per-page native/ocr text artifacts
- persisted rawdict artifacts where available

Do not treat raw PDF re-extraction as the default Phase 02 path.
Prefer persisted Phase 01 artifacts as the source of truth.

Objectives:
1. implement heading candidate extraction from persisted page artifacts
2. implement deterministic heading scoring using explicit signals:
   - numbering patterns
   - line isolation
   - short-line bias
   - title-case / uppercase heuristics
   - punctuation penalties
   - repeated header/footer suppression
   - TOC overlap when selected outline exists
   - rawdict/layout cues only when available
3. implement hierarchy assembly from:
   - selected outline when high-quality and complete
   - inferred heading candidates when outline is missing, partial, or low-confidence
   - hybrid reconciliation when outline and inferred candidates partially agree
4. implement deterministic page-span consolidation:
   - node starts at its heading anchor
   - node ends before the next sibling or ancestor-closing heading
   - descendants must remain within parent spans
   - pages not assignable to any node must be emitted as explicit unassigned spans
5. implement anchor extraction for each node from grounded source text
6. implement verification rules:
   - title exact-normalized match first
   - bounded approximate match second
   - no impossible level jumps
   - full page coverage or explicit unassigned spans
   - no committed node without provenance
7. implement bounded LLM-assisted repair only for:
   - title normalization
   - limited adjacent-level ambiguity resolution
   - partial TOC repair where deterministic evidence is insufficient but localized

Rules:
- deterministic artifact-driven logic first
- LLM repair must be bounded, typed, and auditable
- LLM repair must never invent page spans or unseen sections
- no direct commit of unverified nodes
- every committed node must have page spans
- every committed node must have provenance
- every ambiguous or unresolved case must be emitted explicitly, not silently absorbed

Required models / artifacts:
- HeadingCandidate
- HeadingScoreBreakdown
- HierarchyNode
- HierarchyBuildReport
- UnassignedPageSpan
- NodeAnchor
- VerificationReport
- RepairDecision

Suggested module split:
- headings.py
- hierarchy.py
- anchors.py
- verify.py
- repair.py
- service.py

Required tests:
- broken/partial TOC recovery
- nested numbering patterns
- false heading suppression
- repeated header/footer suppression
- unassigned-page detection
- hybrid outline + inferred-heading reconciliation
- rerun stability
- typed repair-envelope validation

Validation required before completion:
- formatter check
- lint
- type-check
- hierarchy integration tests
- verification regression tests

Return:
- changed files
- validation output
- unresolved ambiguity classes

Status:
- completed on 2026-03-11
- deterministic artifact-driven tree synthesis, explicit unassigned-page spans, typed repair
  artifacts, rerun indexing, committed Phase 02 fixtures, notebook execution harness, and
  verification coverage added
- closeout-hardened on 2026-03-11 with namespace-global tree-run registry indexing, literal
  heading-offset preservation, nth-occurrence outline anchoring, tree-specific verification
  results, reconciled candidate accounting, synthetic fixture policy documentation, and enforced
  notebook structure markers
