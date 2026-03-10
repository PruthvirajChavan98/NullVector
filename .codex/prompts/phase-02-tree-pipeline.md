# Codex Prompt — Phase 02 Tree Pipeline

You are working on StrataForge.

Mission:
Implement hierarchy synthesis, grounding, and verification on top of the deterministic parser substrate.

Objectives:
1. implement heading candidate extraction
2. implement heading scoring using deterministic signals first
3. implement hierarchy assembly from:
   - extracted outline if available
   - inferred heading candidates if outline missing or partial
4. implement page-span consolidation for each node
5. implement anchor extraction for each node
6. implement verification rules:
   - title appears or approximately matches in source span
   - no impossible level jumps
   - page coverage is complete or explicitly marked unassigned
7. implement repair hooks for bounded LLM-assisted normalization only where deterministic logic is insufficient

Rules:
- deterministic logic first
- LLM repair must be bounded, typed, and auditable
- no direct commit of unverified nodes
- every committed node must have page spans
- every committed node must have provenance

Required tests:
- broken/partial TOC recovery
- nested numbering patterns
- false heading suppression
- unassigned-page detection
- rerun stability

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

