# .codex

This folder is the NullVector project-local Codex control plane.

Authoritative persistent repo context lives in `../AGENTS.md`.
This folder supplements `AGENTS.md` with scoped operating materials, local Codex config, and
project-scoped custom agents.

## Layout

- `rules/` => stable engineering rules Codex must follow
- `prompts/` => phase-scoped execution prompts
- `templates/` => reusable task templates and checklists
- `config.toml` => repo-local Codex agent fan-out settings
- `agents/` => project-scoped custom agents

The official project-scoped custom agent directory is `.codex/agents/`.

## Agent Catalog

### `repo_guardian`

Read-only policy and delivery guardian.

Use it for:
- checking whether a task needs preflight, sequential-thinking, web search, notebook maintenance,
  or `CHANGE_DIFF.md`
- reviewing a patch against `AGENTS.md` and `.codex/rules/`
- catching missing validation evidence or missing delivery artifacts

### `docs_researcher`

Read-only documentation and release-status specialist.

Use it for:
- current Codex, OpenAI, MCP, SDK, or model behavior
- vendor docs lookup before implementation decisions
- verifying version-sensitive claims with citations

### `ingest_acquisition_builder`

Implementation agent for ingest and acquisition work.

Primary ownership:
- `src/nullvector/ingest/**`
- acquisition-facing domain models required by the task
- related ingest and acquisition tests

### `tree_semantic_builder`

Implementation agent for tree and semantic work.

Primary ownership:
- `src/nullvector/tree/**`
- `src/nullvector/semantic/**`
- related tree, summarization, and decomposition tests

### `llm_gateway_builder`

Implementation agent for the typed LLM gateway.

Primary ownership:
- `src/nullvector/llm/**`
- related gateway tests and fixtures

### `retrieval_export_builder`

Implementation agent for retrieval and export surfaces.

Primary ownership:
- `src/nullvector/retrieval/**`
- `src/nullvector/export/**`
- related retrieval and export tests

### `storage_observability_builder`

Implementation agent for persistence and runtime visibility.

Primary ownership:
- `src/nullvector/storage/**`
- `src/nullvector/observability/**`
- related storage and integration tests

### `test_notebook_verifier`

Validation-focused agent.

Use it for:
- running requested checks
- deciding whether `notebooks/progress.ipynb` must be updated for a change
- verifying `CHANGE_DIFF.md` completeness and delivery readiness

## Operating Rules

- Repo-wide policy stays in `AGENTS.md` and the existing `.codex/rules/` plus phase prompts.
- Custom agents should stay narrow and opinionated rather than duplicating the full repository
  contract.
- Builder agents should remain inside owned files unless the parent explicitly widens scope.
- Builder agents must not revert unrelated user changes.
- Validation and docs agents should be evidence-first and avoid implementation unless explicitly
  asked.

## Example Prompts

- `Use repo_guardian to review this task against NullVector repo policy before we edit anything.`
- `Ask docs_researcher to verify the latest official Codex docs for subagents and config keys.`
- `Have ingest_acquisition_builder implement this acquisition manifest change and list the tests it touched.`
- `Use tree_semantic_builder to handle this summarization-only change and keep the scope inside tree/semantic files.`
- `Have llm_gateway_builder update the gateway contract and call out any audit or retry behavior changes.`
- `Ask retrieval_export_builder to trace the retrieval path for this ranking regression before proposing a fix.`
- `Use storage_observability_builder for this persistence and eventing change, then summarize migration risk.`
- `Run test_notebook_verifier after the patch and tell me whether the progress notebook or CHANGE_DIFF entry is still missing anything.`
