# Title

PageIndex Import 06: Explicit Tree-Search Retrieval Mode

## Status

`recommended`

## Why This Comes From PageIndex

PageIndex’s core product framing is “reason over the tree,” not just “rank flattened chunks.”

- PageIndex evidence:
  - `/home/pruthvi/projects/github/PageIndex/README.md`
    - frames retrieval as reasoning-based tree search
  - `/home/pruthvi/projects/github/PageIndex/tutorials/tree-search/README.md`
    - shows an LLM selecting relevant node IDs from the document tree

The right NullVector import is a first-class retrieval mode that traverses node cards and summaries hierarchically before falling back to evidence-level retrieval.

## Current NullVector State

NullVector already persists the tree information needed for hierarchical traversal, but current retrieval is organized around evidence units rather than tree-navigation traces.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/src/nullvector/tree/service.py`
    - persists node cards and node summaries
  - `/home/pruthvi/projects/NullVector/src/nullvector/tree/hierarchy.py`
    - projects committed nodes into node cards
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/build.py`
    - turns nodes and summaries into persisted RetrievalEvidence entries
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/planner.py`
    - plans modality and structural intent, but not hierarchical tree traversal
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/service.py`
    - searches flattened units in a document-scoped corpus

NullVector therefore has the data model for tree search, but not the runtime concept.

## User Problem And Outcome

For long structured documents, users want the system to explain:

- which parts of the tree it explored
- why it descended into specific sections
- which nodes led to the final evidence

The desired outcome is:

- a tree-search mode that navigates node cards and summaries
- explicit traversal traces
- better alignment with structure-heavy documents before evidence ranking

## Proposed Capability

Add a new retrieval mode: `TreeSearchService`.

The v1 system should:

- operate on an existing `TreeBuildManifest`
- use node cards and node summaries as the search frontier
- descend the hierarchy step-by-step
- stop when it reaches:
  - high-confidence answer-bearing nodes, or
  - leaf nodes that can be mapped into existing RetrievalEvidence entries
- return a typed traversal trace plus candidate evidence

This is additive. It does not replace the current flattened retrieval service.

## Interfaces And Types

Add:

- `TreeSearchRequest`
  - `query`
  - `tree_manifest_path`
  - `retrieval_manifest_path`
  - `max_depth`
  - `max_frontier_size`
  - `max_selected_nodes`
  - `use_gateway`
- `TreeSearchFrontierNode`
  - `node_id`
  - `title`
  - `page_span`
  - `summary_text`
  - `keywords`
- `TreeSearchTraceStep`
  - `step_index`
  - `frontier_node_ids`
  - `selected_node_ids`
  - `selection_reason`
  - `termination_signal`
- `TreeSearchCandidate`
  - `node_id`
  - `page_span`
  - `retrieval_unit_ids`
  - `score`
- `TreeSearchResponse`
  - `trace`
  - `selected_nodes`
  - `retrieval_hits`
  - `search_mode`
    - `deterministic`
    - `llm`

Add service:

- `TreeSearchService`
  - `search(request: TreeSearchRequest) -> TreeSearchResponse`

## End-to-End Data Flow

1. Load the tree manifest and retrieval manifest.
2. Load node cards and node summaries from the tree artifacts.
3. Build a parent/child adjacency map from committed nodes.
4. Construct the initial frontier from root-level or top-level nodes.
5. For each step:
   - rank the frontier
   - select one or more nodes
   - either descend to children or stop if the node is sufficiently specific
6. Map selected nodes into existing RetrievalEvidence entries, especially NODE_TEXT and NODE_SUMMARY evidence.
7. Optionally pass the retrieved evidence into `RetrievalQAService`.
8. Return a typed trace for auditability and debugging.

The deterministic fallback should use title, summary, and keyword overlap against the query. The LLM mode should only decide frontier ranking and node selection.

## Storage And Artifact Impact

The default response path can be in-memory only.

Optional persisted artifacts for auditable search sessions:

- `tree-search/trace.json`
- `tree-search/results.json`

These should be query-scoped retrieval artifacts, not changes to tree or retrieval manifests.

## LLM And Prompt Boundary

If `use_gateway=True`, the gateway’s role is narrow:

- given a bounded frontier of node cards/summaries
- return:
  - relevant node IDs
  - selection reasons
  - stop/descend signal

The gateway must not:

- open source PDFs
- invent new nodes
- bypass the typed response model

Structured outputs should validate into a frontier-selection response model.

## Failure Modes And Guardrails

- If node cards are missing, fail loudly rather than attempting tree search over raw text.
- If node summaries are missing, fall back to title/keyword-only ranking.
- If the tree is too wide, cap the frontier and log the truncation.
- If the gateway returns unknown node IDs, fail validation.
- If the tree search cannot confidently narrow the tree, hand off to the existing retrieval service rather than looping indefinitely.

## Testing And Acceptance

Implementation must include:

- unit tests for adjacency-map construction
- unit tests for deterministic frontier ranking
- unit tests for trace-step construction
- integration test that tree search selects nodes and maps them to RetrievalEvidence entries
- notebook coverage in `notebooks/progress.ipynb` showing:
  - selected nodes
  - traversal trace
  - downstream retrieval or QA result

Acceptance criteria:

- tree search can explain its traversal
- the response can be consumed without reading the raw tree JSON manually
- deterministic fallback and LLM-assisted modes share the same public response shape

## Rollout Order

Recommended after core retrieval remains stable.

Suggested order:

1. tree-search types
2. deterministic frontier ranking
3. trace response
4. LLM-assisted frontier selection
5. QA integration

Preference-aware search depends on this doc and should be layered on top rather than merged into the base implementation.

## Non-Goals

- no replacement for `RetrievalService`
- no MCTS or rollouts in v1
- no unbounded agent loop
- no direct provider-specific prompt helpers
