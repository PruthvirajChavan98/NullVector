# Title

PageIndex Import 08: Tree Thinning And Serving Compaction

## Status

`recommended`

## Why This Comes From PageIndex

PageIndex’s Markdown path includes explicit thinning controls to reduce tree size for retrieval use.

- PageIndex evidence:
  - `/home/pruthvi/projects/github/PageIndex/run_pageindex.py`
    - `--if-thinning`
    - `--thinning-threshold`
    - `--summary-token-threshold`
  - `/home/pruthvi/projects/github/PageIndex/pageindex/page_index_md.py`
    - `tree_thinning_for_index(...)`
    - conditional thinning during Markdown tree build

The valuable import for NullVector is not to mutate the source tree. It is to produce a second, lighter serving tree optimized for interactive retrieval.

## Current NullVector State

NullVector already has mechanisms for large trees, but they focus on correctness and summarization, not serving compaction.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/src/nullvector/domain/tree.py`
    - `TreeSettings` has max leaf pages and token limits
  - `/home/pruthvi/projects/NullVector/src/nullvector/semantic/summarize.py`
    - generates node summaries
  - `/home/pruthvi/projects/NullVector/src/nullvector/tree/service.py`
    - persists canonical node cards and summaries

There is no first-class “serving tree” artifact that is smaller than the canonical tree and explicitly marked as a derivative representation.

## User Problem And Outcome

Interactive retrieval over large trees can be expensive. Users want a smaller tree for navigation and serving without losing the full canonical tree needed for audit and downstream correctness.

The desired outcome is:

- preserve the canonical tree untouched
- generate a smaller derived tree for serving and search
- maintain a mapping back to canonical node IDs

## Proposed Capability

Add a post-tree compaction stage that produces a serving-oriented tree representation.

The v1 compactor should:

- merge low-value intermediate nodes
- keep high-signal headings
- retain node ID mapping back to canonical nodes
- use summaries to replace low-detail branches where appropriate

The compactor runs after canonical tree build and optional summarization.

## Interfaces And Types

Add:

- `TreeCompactionRequest`
  - `tree_manifest_path`
  - `compaction_run_id`
  - `settings`
- `TreeCompactionSettings`
  - `max_children_per_node`
  - `min_tokens_for_preservation`
  - `min_heading_signal`
  - `require_summaries`
- `CompactedTreeNode`
  - `serving_node_id`
  - `canonical_node_ids`
  - `title`
  - `summary_text`
  - `page_span`
  - `children`
- `CompactedTreeManifest`
  - `document_id`
  - `source_tree_manifest_path`
  - `compacted_tree_path`
  - `node_mapping_path`

Add service:

- `TreeCompactionService`
  - `compact(request: TreeCompactionRequest) -> CompactedTreeManifest`

## End-to-End Data Flow

1. Load canonical tree artifacts.
2. Load node summaries and node cards.
3. Score nodes for preservation or collapse using:
   - heading level
   - branch width
   - span coverage
   - summary availability
4. Emit a compacted tree.
5. Emit a mapping from serving nodes to canonical node IDs.
6. Persist the compaction manifest and artifacts.

The serving tree is a derived artifact only. All evidence retrieval must still be able to map back to canonical nodes before citation or QA.

## Storage And Artifact Impact

Use a new run type: `tree_compaction`.

Persist:

- `compaction/compacted-tree.json`
- `compaction/node-mapping.json`
- `compaction/manifest.json`

Do not overwrite:

- canonical committed nodes
- node cards
- node summaries
- tree manifest

## LLM And Prompt Boundary

Base compaction should be deterministic.

- summaries may be consumed as input
- the compactor should not call the gateway in v1

If future LLM-assisted compaction is explored, it should be a separate method enum and a later phase.

## Failure Modes And Guardrails

- If summaries are required and missing, fail clearly rather than compacting with poor signals.
- If compaction would collapse the tree to an unusably shallow shape, fail or warn based on strictness settings.
- Every serving node must map back to at least one canonical node ID.
- Retrieval and QA must never cite a serving-only node ID without canonical mapping.

## Testing And Acceptance

Implementation must include:

- unit tests for preservation/merge heuristics
- unit tests for canonical mapping completeness
- integration tests showing retrieval from the compacted tree still maps to canonical evidence
- notebook coverage in `notebooks/progress.ipynb` showing:
  - canonical tree summary
  - compacted tree summary
  - mapping back to canonical nodes

Acceptance criteria:

- compaction reduces serving complexity
- canonical tree remains unchanged
- every serving decision is traceable back to canonical nodes

## Rollout Order

Recommended after:

1. stable tree build
2. stable summarization
3. preferably base tree search

This is a serving optimization and should not block core pipeline completeness.

## Non-Goals

- no mutation of the canonical tree
- no hidden replacement of canonical node IDs
- no mandatory use of compacted trees in retrieval
- no LLM-assisted compaction in v1
