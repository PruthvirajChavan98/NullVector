# Title

PageIndex Import 07: Preference-Aware Tree Search

## Status

`recommended`

## Why This Comes From PageIndex

PageIndex explicitly calls out the ability to inject user preferences or expert knowledge into tree search prompts.

- PageIndex evidence:
  - `/home/pruthvi/projects/github/PageIndex/tutorials/tree-search/README.md`
    - has a dedicated “Integrating User Preference or Expert Knowledge” section
    - describes retrieving relevant preference snippets before tree search

The import for NullVector is a controlled, typed way to bias tree traversal without contaminating the canonical tree or hiding the provenance of those biases.

## Current NullVector State

NullVector currently has no explicit preference or policy layer in retrieval.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/planner.py`
    - deterministic query planning only
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/service.py`
    - no concept of preference snippets or policy hints
  - `/home/pruthvi/projects/NullVector/src/nullvector/llm/service.py`
    - strong typed gateway boundary already exists and can safely carry structured prompt context

This feature therefore extends the proposed tree-search mode rather than modifying current retrieval service internals.

## User Problem And Outcome

In many domains, the “most useful” section is not purely determined by lexical relevance. Users want retrieval to honor:

- domain rules
- customer-specific preferences
- analyst playbooks
- organization-specific section priorities

The desired outcome is:

- inject preferences at retrieval time
- keep preference provenance visible
- bias node selection without changing the tree artifacts themselves

## Proposed Capability

Add a preference-aware overlay on top of `TreeSearchService`.

The v1 model:

- retrieve a small set of relevant preference snippets for the query
- include those snippets in frontier ranking
- record which snippets influenced the search
- keep preference injection optional and query-scoped

This is a retrieval-time policy layer, not a tree mutation system.

## Interfaces And Types

Add:

- `PreferenceSnippet`
  - `preference_id`
  - `scope`
    - `global`
    - `tenant`
    - `user`
    - `domain_rule`
  - `text`
  - `priority`
  - `metadata`
- `PreferenceSelectionRequest`
  - `query`
  - `snippets`
  - `limit`
- `PreferenceSelectionResult`
  - `selected_snippets`
  - `selection_reason`
- `PreferenceRepository` protocol
  - load snippets for the current caller or environment
- `PreferenceAwareTreeSearchRequest`
  - base `TreeSearchRequest`
  - `preference_snippets`
  - `max_preference_snippets`
- `PreferenceAwareTreeSearchTraceStep`
  - extends trace with `applied_preference_ids`

Add services:

- `PreferenceSelectionService`
  - ranks which snippets are relevant to the query
- `PreferenceAwareTreeSearchService`
  - wraps or extends `TreeSearchService`

## End-to-End Data Flow

1. Load candidate preference snippets from a repository or caller input.
2. Rank or filter the snippets down to a bounded set.
3. Run tree search with:
   - query
   - bounded frontier
   - bounded preference set
4. Persist or return a trace that shows:
   - which snippets were applied
   - which nodes were selected under their influence
5. Continue with existing evidence retrieval and QA.

The preference layer must remain optional. If no snippets are provided, behavior should match base tree search exactly.

## Storage And Artifact Impact

The source of truth for preferences should remain external to NullVector in v1.

Optional artifacts:

- `tree-search/preference-selection.json`
- `tree-search/preference-aware-trace.json`

NullVector should record the snippet IDs and texts used during a search session, but it should not become the canonical preference store in v1.

## LLM And Prompt Boundary

The gateway should see preference snippets only as bounded contextual hints.

- input:
  - query
  - frontier node cards/summaries
  - selected preference snippets
- output:
  - selected node IDs
  - reason
  - preference IDs applied

Guardrails:

- cap preference count aggressively
- require typed response fields for applied preference IDs
- never allow the model to invent preference snippets

## Failure Modes And Guardrails

- If preferences are too broad or too many, the service must truncate and log the truncation.
- If selected preference IDs are unknown, fail validation.
- If preference-aware search produces worse confidence than base tree search, allow a deterministic fallback to base search.
- Preferences must bias selection, not override structural grounding or citation provenance.

## Testing And Acceptance

Implementation must include:

- unit tests for preference snippet selection
- unit tests ensuring zero-snippet behavior equals base tree search
- integration tests showing preference-aware ranking changes node choice
- notebook coverage in `notebooks/progress.ipynb` showing:
  - base tree search result
  - preference-aware tree search result
  - applied preference IDs in the trace

Acceptance criteria:

- preference-aware mode is additive and auditable
- base behavior is unchanged when no preferences are provided
- provenance is preserved end-to-end

## Rollout Order

Depends on Doc 06.

Suggested order:

1. base tree search
2. preference repository/selection
3. preference-aware prompt/trace layer

This should ship only after base tree search is stable enough to measure whether preferences help.

## Non-Goals

- no fine-tuning or embedding retraining
- no persistence of preferences as canonical tree metadata
- no silent override of base retrieval safety rules
- no preference-driven answer synthesis separate from evidence retrieval
