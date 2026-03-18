# Title

PageIndex Import 09: Lightweight CLI Workflow For Quick Tree Builds

## Status

`recommended`

## Why This Comes From PageIndex

PageIndex’s usability advantage is obvious in its single-command workflow.

- PageIndex evidence:
  - `/home/pruthvi/projects/github/PageIndex/run_pageindex.py`
    - one CLI entrypoint for PDF or Markdown to tree output
  - `/home/pruthvi/projects/github/PageIndex/README.md`
    - documents quick CLI usage directly

The NullVector import worth making is not to turn the framework into a CLI-first product. It is to add an edge-only workflow that makes quick experimentation far easier.

## Current NullVector State

NullVector’s architecture is library-first and intentionally not CLI-centered.

- NullVector evidence:
  - `/home/pruthvi/projects/NullVector/docs/architecture.md`
    - explicitly says NullVector is a Python library, not a CLI entrypoint
  - `/home/pruthvi/projects/NullVector/src/nullvector/ingest/acquisition_service.py`
  - `/home/pruthvi/projects/NullVector/src/nullvector/tree/service.py`
  - `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/build.py`

Today, users need to assemble these services manually or rely on notebooks. That is powerful but heavy for simple “just build the tree” workflows.

## User Problem And Outcome

Users evaluating NullVector often want to do one of three things quickly:

- ingest a document
- build a tree
- optionally build retrieval artifacts

The desired outcome is:

- a thin workflow wrapper for quick local usage
- no weakening of the library-first architecture
- no requirement to manually orchestrate multiple services for the common case

## Proposed Capability

Add an edge-only quickstart CLI script that orchestrates:

- acquisition
- tree build
- optional retrieval corpus build
- optional document description build once Doc 01 exists

Implementation decision:

- this should live as a repo-level tool or `scripts/` entrypoint
- it should not redefine core contracts
- it should call existing services directly

## Interfaces And Types

Do not add new core domain types for the CLI itself.

Add a thin script entrypoint such as:

- `scripts/nullvector_quickstart.py`

Arguments:

- `--source-path`
- `--source-kind`
  - `pdf`
  - `markdown`
- `--acquisition-run-id`
- `--tree-run-id`
- `--summarize`
- `--build-retrieval`
- `--build-description`
- `--storage-backend`
- `--artifact-root`

Output behavior:

- print manifest paths
- print key stats
- optionally print a short tree summary

## End-to-End Data Flow

1. Parse CLI args.
2. Build `AcquisitionRequest`.
3. Run acquisition.
4. Build `TreeBuildRequest`.
5. Run tree build.
6. Optionally:
   - run retrieval corpus build
   - run document description build
7. Print manifest refs and summary stats.

The CLI is an orchestration wrapper only. All real work stays in the existing services.

## Storage And Artifact Impact

No new artifact families are required for the CLI itself.

The script should only create the artifacts already produced by the services it invokes.

If the implementation includes a small “last run summary” file for convenience, it must live outside canonical artifact paths and must not become part of the contract.

## LLM And Prompt Boundary

The CLI should not introduce any new prompt or gateway behavior.

- if `--summarize` is set, it uses the existing summarization path
- if `--build-description` is set, it uses the existing description-builder path once implemented

No direct provider helpers, raw prompts, or special CLI-only LLM code should exist.

## Failure Modes And Guardrails

- Surface typed runtime errors directly instead of swallowing them behind friendly text.
- For batch-fatal gateway problems, the CLI should exit non-zero and print the typed error name.
- Do not silently auto-enable optional stages.
- If the source kind and provider are incompatible, fail before work starts.

## Testing And Acceptance

Implementation must include:

- script smoke tests
- integration test invoking the quickstart script against fixtures
- notebook note in `notebooks/progress.ipynb` pointing to the CLI flow as an optional manual path

Acceptance criteria:

- a new user can run one command and receive manifest refs
- the script remains thin and delegates to core services
- the library contracts remain the same with or without the CLI

## Rollout Order

Implement last or near last.

This is a usability layer over existing capabilities and should not block the underlying feature work.

## Non-Goals

- no conversion of NullVector into a CLI-first application
- no new business logic in the script
- no hidden defaults that diverge from service behavior
- no bespoke provider integrations at the edge
