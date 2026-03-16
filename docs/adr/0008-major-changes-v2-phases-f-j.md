# ADR 0008: major-changes-v2 Phases F-J

## Status
Accepted

## Context
NullVector already had a parallel v2 acquisition and projection runtime, but the remaining
migration work still left four architectural gaps:

- semantic services still lived under `tree/` and had no tokenizer boundary
- multimodal enrichment had no typed, isolated gateway path
- observability remained placeholder-only
- external ecosystem exports had no edge-only boundary

The main runtime also still exposed the legacy parse substrate from the primary `ingest` entrypoint.

## Decision
Adopt the following final migration structure:

- semantic summarization and decomposition move into `nullvector.semantic`
- token accounting is mediated by a tokenizer protocol with a heuristic default and an optional
  exact tokenizer
- multimodal/VLM enrichment is handled through the main `nullvector.llm` gateway surface using
  attachment inputs
- structured runtime events are emitted through logger helpers under
  `nullvector.observability`
- LangChain and LlamaIndex exporters live under `nullvector.export` and remain optional,
  edge-only helpers
- the primary runtime is acquisition/projection-only; the legacy parse substrate is retained only
  under `nullvector.compat.legacy_parse`

## Consequences

### Positive
- tree builds now have a single acquisition-manifest entrypoint
- semantic operations can evolve token budgeting independently of the tree package
- multimodal enrichment is bounded and non-authoritative by contract
- observability is explicit, typed, and testable
- external framework integrations cannot leak their dependencies into core modules

### Negative
- the repository now carries a temporary deprecated compatibility surface for legacy parse tests
- acquisition-backed parity still depends on projection fidelity for headings, anchors, and TOC cues
- optional exact tokenizers and third-party exporters remain environment-sensitive by design
