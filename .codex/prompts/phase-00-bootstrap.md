# Codex Prompt — Phase 00 Bootstrap

You are working on NullVector.

Mission:
Create the production bootstrap for a CPU-only hierarchical PDF ingestion system.
Do not implement retrieval.
Do not implement speculative features not required by this phase.

Objectives:
1. create the initial repository skeleton
2. add strict typed domain models for:
   - PageLedgerRow
   - PageSpan
   - NodeCard
   - VerificationResult
   - ParseJobState
3. add local tooling configuration for:
   - formatting
   - linting
   - type-checking
   - tests
4. add CI-ready commands
5. add ADR stubs
6. add fixture directories for PDFs and expected parse outputs

Constraints:
- Python 3.11+
- strict typing
- zero deprecation warnings
- no sync DB code
- no regex JSON repair

Required outputs:
- file tree summary
- exact commands to validate
- any blockers
- residual risks

Validation required before completion:
- formatter check
- lint
- type-check
- tests

Status:
- completed on 2026-03-10
- bootstrap skeleton, typed contracts, local validation commands, ADR scaffolding, and fixture
  directories added
