# ADR 0003: Artifact-Driven Tree Pipeline with Explicit Coverage Gaps and Typed Repair Stub

- Status: accepted
- Date: 2026-03-11

## Context

Phase 02 needs deterministic hierarchy synthesis on top of persisted Phase 01 parser artifacts. The
tree layer must stay artifact-driven, preserve rerun stability, make title anchoring and page
coverage explicit, and define a repair boundary without prematurely introducing a real LLM gateway.

## Decision

Implement the Phase 02 tree pipeline with:

- committed synthetic parse-artifact fixture directories as the primary test substrate
- deterministic heading extraction from persisted page text plus sampled rawdict artifacts
- nth-occurrence line anchoring, with rawdict-backed line grouping overriding plain-text occurrence
  matching when available
- tuneable trust and scoring thresholds in `TreeSettings`
- namespace-global `tree_run_id` indexing under a resolved `_tree_runs/` registry while keeping
  tree outputs under each parse artifact root
- no synthetic document root; uncovered pages are emitted as explicit `UnassignedPageSpan` artifacts
- deterministic `node_id` generation from document id, normalized path, level, heading anchor, and
  span start page
- bounded approximate title verification with explicit match tiers
- a typed repair boundary and `NoopRepairEngine` default for Phase 02
- notebook execution through an `nbclient` / `nbformat` helper script instead of ad hoc code-cell
  execution

## Consequences

- Phase 02 stays coupled to persisted parser artifacts instead of drifting back into PDF extraction.
- Tree outputs are replayable and diffable because tree runs have their own manifest plus a
  namespace-global registry entry keyed by parse-artifact identity and settings.
- Coverage gaps are visible and testable rather than being hidden behind a synthetic root node.
- Repair artifacts are available now, but meaningful proposals still depend on the Phase 03 LLM
  gateway.
- Phase 02 fixtures can intentionally carry richer rawdict coverage than strict Phase 01 sampling,
  so they should not be reused as parser-fidelity assertions.
- Notebook execution becomes a real validation surface and adds a small Jupyter-stack dependency to
  development and test environments.
