# Repository Structure Audit

## Purpose

This document validates the current NullVector repository layout and defines the target
end-state structure for a production-grade Python framework repo.

The goal is not to reorganize code in this document. The goal is to make structure
ownership explicit, separate authored assets from generated runtime output, and give
contributors deterministic placement rules for future work.

## Audit Rubric

| Criterion | Pass condition |
| --- | --- |
| Ownership clarity | Every top-level directory has one obvious purpose and one owner class. |
| Authored vs generated separation | Source code, docs, tests, fixtures, notebooks, and runtime outputs do not share the same directory tree without an explicit exception policy. |
| Package boundary clarity | `src/nullvector/` is organized by subsystem or phase, with public DX surfaces distinct from subsystem internals. |
| Fixture discipline | Reusable committed inputs and goldens live under `fixtures/`, not under runtime or debug directories. |
| Ignore policy alignment | `.gitignore` and tracked content agree on which directories are runtime-only. |
| Documentation alignment | `README.md` and `docs/architecture.md` describe the real repository and product surface. |
| Future placement rules | A new engineer can place a new file without guessing between multiple plausible directories. |

## Current-State Audit

### Top-Level Classification

| Path | Class | Status | Notes |
| --- | --- | --- | --- |
| `src/` | Framework source | Pass | Package layout is phase-oriented and readable. |
| `tests/` | Automated validation | Pass | Split by test style and subsystem. |
| `fixtures/` | Committed reusable inputs and expected outputs | Pass | Dedicated fixture space exists. |
| `docs/` | Authored technical documentation | Pass | Correct home for architecture, ADRs, legal docs, standards, and structure policy. |
| `scripts/` | Maintained operator and development scripts | Pass | Small and bounded. |
| `tasks/` | Workflow/task tracking | Pass | Repo-level process metadata. |
| `.agents/`, `.claude/`, `.codex/` | Developer tooling and agent metadata | Pass | Legitimate repo metadata, not framework runtime output. |
| `.artifacts/` | Generated runtime output | Pass | Already ignored and is the best candidate for the canonical runtime root. |
| `cookbook/` | Authored cookbook notebooks plus supporting assets | Fail | Mixed with tracked/generated runtime trees such as `.tree_tmp/`, `nv_workspace/`, `nullvector_artifacts/`, `.artifacts/`, `artifacts/`, and `_tmp/`. |
| `notebooks/` | Maintained notebooks | Needs follow-up | Authored notebooks are valid, but artifact subtrees must stay generated-only and clearly segregated. |
| `artifacts/` | Runtime output | Fail | Tracked even though `.gitignore` already ignores `artifacts/`. |
| `tmp/` | Runtime and debug output | Fail | Tracked even though `.gitignore` already ignores `tmp/`. |
| `.tree_tmp/` | Scratch runtime output | Needs consolidation | Local ignored scratch root exists at repo top level while related runtime trees are tracked elsewhere. |
| `document-selection/` | Runtime observe outputs | Fail | Tracked result artifacts are sitting at repo root without a durable authored purpose. |
| `tree-search/` | Runtime observe outputs | Fail | Same problem as `document-selection/`. |
| `features/` | Planning/spec documents | Needs relocation | Authored content, but outside the repo's documented docs taxonomy. |

### Package-Level Validation for `src/nullvector/`

| Criterion | Status | Notes |
| --- | --- | --- |
| Phase-oriented subsystem packaging | Pass | `ingest/`, `tree/`, `llm/`, `retrieval/`, `semantic/`, `storage/`, `observability/`, `export/`, and `domain/` are coherent. |
| Public DX surface separated from subsystem packages | Pass | `client.py`, `cli.py`, `presets.py`, `errors.py`, and `__init__.py` sit at package root. |
| Shared internals are limited and cross-cutting | Pass with caution | `_client_utils.py`, `_text.py`, and `_hierarchy.py` are used across subsystems and still fit the shared-internal pattern. |
| Generated artifacts inside tracked package space | Pass | No tracked runtime trees under `src/nullvector/`. |
| Duplicate package surfaces | Pass with follow-up | The working tree contains ignored cache residue under some package dirs, but no tracked duplicate package tree was found. |

### Observed Anomalies Requiring Cleanup Decisions

1. `cookbook/.tree_tmp/` is tracked runtime output under authored cookbook space.
2. `cookbook/nv_workspace/` and `cookbook/nullvector_artifacts/` are runtime workspaces tracked inside cookbook content.
3. `artifacts/` and `tmp/` are tracked despite being ignored by policy.
4. `document-selection/` and `tree-search/` are tracked runtime result roots at the repo top level.
5. `cookbook/cookbook/` and `notebooks/notebooks/` exist as duplicate placeholder directories with no evident authored content.
6. `features/` holds authored roadmap/spec material but sits outside the repo's main documentation taxonomy.

## Target End-State Layout

### Canonical Top-Level Taxonomy

```text
/
|- .agents/              # developer and agent metadata
|- .claude/              # tool metadata
|- .codex/               # tool metadata
|- .artifacts/           # canonical ignored runtime/output root
|- src/                  # framework source code
|- tests/                # automated tests
|- fixtures/             # committed reusable fixtures and goldens
|- docs/                 # architecture, ADRs, standards, legal, roadmap/spec docs
|- scripts/              # maintained developer/operator scripts
|- cookbook/             # authored cookbook notebooks and checked-in supporting assets only
|- notebooks/            # maintained notebooks and optionally checked-in executed examples by policy
|- tasks/                # workflow tracking
|- README.md
|- pyproject.toml
|- uv.lock
```

### Runtime Output Policy

`.artifacts/` becomes the single canonical ignored runtime root for local runs, notebook
execution, cookbook execution, observability captures, and ad hoc debug output.

Examples of target runtime destinations:

- `.artifacts/cookbook/...`
- `.artifacts/notebooks/...`
- `.artifacts/runtime-observe/document-selection/...`
- `.artifacts/runtime-observe/tree-search/...`
- `.artifacts/debug/...`

The following should not remain as long-term top-level tracked runtime roots:

- `artifacts/`
- `tmp/`
- `document-selection/`
- `tree-search/`
- `cookbook/.tree_tmp/`
- `cookbook/nv_workspace/`
- `cookbook/nullvector_artifacts/`

### Documentation Taxonomy

- `docs/` owns architecture, standards, ADRs, legal docs, and roadmap/spec docs.
- `features/` should be rehomed under a `docs/` subdirectory such as `docs/features/` or
  `docs/roadmap/`.
- `cookbook/` owns authored how-to notebooks, not execution residue.
- `notebooks/` owns maintained exploratory or validation notebooks, not generic runtime workspaces.

## Placement Rules for Future Contributions

1. New framework code goes under `src/nullvector/<subsystem>/` unless it is a public DX entrypoint.
2. New public DX surfaces belong at `src/nullvector/` only when they are user-facing package
   entrypoints, not subsystem internals.
3. New shared underscore modules are allowed only for cross-cutting helpers used by multiple
   subsystems and should stay rare.
4. New committed reusable inputs and expected outputs go under `fixtures/`.
5. New authored documentation goes under `docs/`, not under ad hoc top-level directories.
6. New cookbook material goes under `cookbook/`; new maintained notebook material goes under
   `notebooks/`.
7. New runtime output must go under `.artifacts/`, never under a new top-level directory.
8. A runtime artifact may be committed only when it is explicitly promoted to fixture or evidence
   status and documented as such.
9. `.gitignore` and tracked content must agree: ignored-style runtime roots must not accumulate
   tracked content.
10. Duplicate nesting such as `cookbook/cookbook/` or `notebooks/notebooks/` is not allowed.

## Cleanup Sequence

1. Freeze the structure policy in docs before moving anything.
2. Correct stale architecture and repository-layout documentation.
3. Choose `.artifacts/` as the canonical runtime root and document it everywhere.
4. Reclassify tracked runtime directories into one of:
   - fixture/evidence that should move under `fixtures/`
   - generated output that should move under `.artifacts/`
   - duplicate/placeholder content that should be removed
5. Remove or relocate duplicate/empty directories such as `cookbook/cookbook/` and
   `notebooks/notebooks/`.
6. Rehome `features/` under `docs/`.
7. Align `.gitignore` with the cleaned structure only after the tracked runtime trees have been
   reclassified.

## Acceptance Criteria

The repository structure passes validation when:

1. Every top-level directory has one explicit purpose.
2. No tracked runtime tree remains in a directory intended for authored source, docs, tests, or
   cookbooks.
3. `src/nullvector/` remains phase-oriented and free of tracked generated artifacts.
4. `README.md` and `docs/architecture.md` accurately describe the current product surface and repo
   organization.
5. A new contributor can answer, without ambiguity:
   - where framework code goes
   - where fixtures go
   - where cookbook/notebook source goes
   - where execution outputs go
