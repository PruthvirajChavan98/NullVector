# ADR 0005: Major Tree Enhancements with TOC Recovery, Strategy Selection, and Pre-Summary Decomposition

- Status: accepted
- Date: 2026-03-11

## Context

The original Phase 02 tree pipeline established deterministic heading extraction, hierarchy
assembly, explicit unassigned spans, and typed repair boundaries, but it did not yet handle
table-of-contents recovery, bounded verification assistance, strategy selection across multiple
hierarchy sources, or subdivision of oversized committed leaf nodes before final summarization.

The repository operating contract requires these changes to remain additive, typed, replayable, and
auditable, without widening the core parser path or introducing hidden network dependencies.

## Decision

Extend the tree pipeline with the following additive capabilities:

- deterministic-first TOC detection over persisted parse artifacts, with typed LLM fallback only for
  ambiguous pages
- bounded TOC parsing and reconciliation into `HeadingCandidate` entries, including logical-to-
  physical page offset calculation
- optional grounded LLM verification assistance only when deterministic title verification returns
  `TitleMatchTier.NONE`
- bottom-up summarization of committed nodes, still opt-in and gateway-backed
- deterministic strategy selection and bounded cascade across outline-only, TOC-derived, and
  inferred-with-assist build attempts
- deterministic-first decomposition of oversized committed leaf nodes before final summarization,
  with optional bounded LLM fallback only when deterministic subdivision yields fewer than two usable
  sub-headings
- final build ordering of:
  - strategy attempt selection
  - initial committed hierarchy
  - decomposition of committed leaves
  - re-verification of decomposed hierarchy
  - node-card projection
  - optional final summarization

## Consequences

- Tree builds now produce additional auditable artifacts such as TOC detection, TOC reconciliation,
  strategy execution reports, LLM verification assists, node summaries, and decomposition reports.
- The selected strategy remains explicit in artifacts, and the main manifest points directly at the
  selected attempt outputs rather than copying them into a second “final” layer.
- Large-node decomposition can improve final hierarchy quality, but verification must tolerate the
  repository’s prefix-truncated parent spans for decomposed children.
- Summaries now describe the final decomposed hierarchy instead of a pre-decomposition tree.
- Existing non-gateway behavior remains deterministic and backward-compatible by default.
