# Title

PageIndex Import 10: Deferred Advanced Search And Runtime Imports

## Status

`deferred`

## Why This Comes From PageIndex

PageIndex surfaces three ideas that are interesting but not good immediate imports into NullVector core:

- MCTS/value-function tree search
- direct OpenAI-style helper APIs for rapid prototyping
- lenient JSON extraction and cleanup as a runtime technique

PageIndex evidence:

- `/home/pruthvi/projects/github/PageIndex/tutorials/tree-search/README.md`
  - mentions value function-based MCTS with LLM tree search
- `/home/pruthvi/projects/github/PageIndex/pageindex/utils.py`
  - exposes `ChatGPT_API`, `ChatGPT_API_async`, and `ChatGPT_API_with_finish_reason`
  - exposes `extract_json(...)`
- `/home/pruthvi/projects/github/PageIndex/pageindex/page_index.py`
  - repeatedly uses helper APIs plus JSON extraction inside core runtime flow

These are real ideas, but they push against NullVector’s current architectural strengths.

## Current NullVector State

NullVector’s current strengths are the exact things these imports would threaten if copied too literally.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/src/nullvector/llm/service.py`
    - typed gateway, retries, auditing, validation, and explicit structured outputs
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/service.py`
    - deterministic retrieval orchestration
  - `/home/pruthvi/projects/NullVector/src/nullvector/docs/architecture.md`
    - layered library-first architecture
  - `/home/pruthvi/projects/NullVector/src/nullvector/domain/retrieval.py`
    - typed retrieval contracts

The central design constraint for this doc is: do not weaken the typed gateway, artifact discipline, or storage boundaries to import PageIndex ideas that primarily optimize for iteration speed.

## User Problem And Outcome

These advanced imports matter for three reasons:

- MCTS could eventually improve hard-query tree navigation
- direct helper surfaces can speed up experiments
- lenient JSON recovery can rescue weak providers or research prototypes

The desired outcome for this doc is not immediate implementation. It is to define exactly why these ideas are deferred, what revisit gates should exist, and what safe shape they would need if ever adopted.

## Proposed Capability

No immediate implementation is recommended.

Instead, record three deferred design tracks that may be revisited once base tree search, document selection, and gateway-backed retrieval are measured in production-like evaluations.

### A. MCTS / Value-Function Tree Traversal

Potential future capability:

- a search policy that evaluates frontier nodes over multiple rollouts
- value scoring over node cards and partial evidence
- explicit traversal budgets and audit traces

Potential interfaces if revisited:

- `TreeSearchPolicy`
- `MctsTreeSearchSettings`
- `TreeSearchRolloutTrace`
- `NodeValueScorer` protocol

#### Why not now

- NullVector does not yet have a first-class base tree-search service to improve upon.
- MCTS adds algorithmic and operational complexity before baseline tree traversal has even been measured.
- It would likely increase latency and observability burden significantly.

#### What would need to be true to revisit

- base tree-search retrieval exists and is benchmarked
- there is evidence that greedy or beam-style traversal underperforms on real documents
- there is a stable trace/audit contract for multi-step search rollouts

#### What parts of NullVector would be at risk

- retrieval latency
- trace and audit volume
- search-result reproducibility

### B. OpenAI-Style Rapid Prototyping Helper Surface

Potential future capability:

- a research-only helper layer for quick prompt experiments
- lightweight wrappers around the typed gateway for notebooks or experiments

Potential interfaces if revisited:

- `ResearchGatewayFacade`
- a non-core `experiments/` or `sandbox/` module outside the main library contract

#### Why not now

- direct helper functions would duplicate `GatewayService` behavior
- they would encourage bypassing audits, validation, and provider abstraction
- the current framework benefits from not having ad hoc prompt transport in core code

#### What would need to be true to revisit

- the helpers live outside core runtime paths
- they are clearly labeled experimental
- they still route through the gateway or are otherwise isolated from production code

#### What parts of NullVector would be at risk

- typed gateway boundaries
- audit completeness
- provider portability

### C. Lenient JSON Recovery Layer

Potential future capability:

- a last-resort parser that tries to recover structured payloads from malformed provider text

Potential interfaces if revisited:

- `StructuredOutputRecoveryPolicy`
- adapter-scoped recovery hooks with explicit metrics and disable-by-default behavior

#### Why not now

- NullVector already has stronger typed structured-output behavior
- recovery-heavy parsing can hide provider regressions and degrade trust in outputs
- it conflicts with the framework’s bias toward fail-loud validation

#### What would need to be true to revisit

- there is a provider or mode that is operationally useful but unreliable with strict structured outputs
- recovery remains off by default
- every recovered payload is explicitly labeled and auditable

#### What parts of NullVector would be at risk

- validation semantics
- user trust in artifact correctness
- debuggability of provider failures

## Interfaces And Types

Do not add these interfaces to core NullVector now.

If revisited later:

- MCTS interfaces belong in retrieval/tree-search extensions
- research helper surfaces belong outside core runtime modules
- recovery hooks belong behind adapter or gateway policy boundaries and must be disabled by default

## End-to-End Data Flow

No v1 data flow is approved for implementation.

If these ideas are revisited:

- MCTS would sit between tree frontier construction and evidence retrieval
- helper surfaces would sit outside core services
- JSON recovery would sit at the adapter/gateway boundary after provider response receipt but before model validation

## Storage And Artifact Impact

No new artifacts should be introduced now.

If revisited:

- MCTS would require rollout traces and search metrics artifacts
- helper surfaces should not create canonical artifacts
- JSON recovery would likely require audit annotations indicating recovered vs strictly validated output

## LLM And Prompt Boundary

This entire doc exists to protect the current LLM boundary.

- do not bypass `StructuredLLMGateway`
- do not normalize direct provider calls inside core runtime paths
- do not silently recover malformed outputs as if they were strictly valid

## Failure Modes And Guardrails

- Accidental implementation of these ideas in core code would blur NullVector’s strongest architecture boundaries.
- Research convenience must not quietly become production runtime policy.
- Any revisit must come with explicit metrics, kill switches, and audit visibility.

## Testing And Acceptance

There is nothing to implement now.

Acceptance for this doc is design clarity:

- the three deferred ideas are documented separately
- each has a clear revisit gate
- each names the NullVector subsystems it could damage if imported naively

If one of these ideas is ever promoted from deferred to recommended, it must get its own standalone implementation spec and no longer live only in this deferred bundle.

## Rollout Order

Do not schedule these in the current near-term roadmap.

Revisit only after:

1. document descriptions and collection selection exist
2. base tree-search retrieval exists
3. performance and quality evaluation data exists for hard-query navigation

## Non-Goals

- no current implementation commitment
- no weakening of the typed gateway
- no shortcut path that bypasses audit and validation
- no experimental feature hiding inside production contracts
