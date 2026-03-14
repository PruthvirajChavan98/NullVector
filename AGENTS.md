# NullVector — Repository Operating Contract

## Mandatory repo context

Before substantive work:
1. Read this `AGENTS.md`
2. Read `.codex/initial_research.md`
3. Read `.codex/rules/runtime-enforcement.md`
4. Read the relevant phase prompt in `.codex/prompts/`
5. If present, run `bash .codex/bin/preflight-codex.sh`

Do not recursively read all files under `.codex/` unless a task explicitly requires it.

## Mandatory notebook progress artifact

NullVector maintains one canonical runnable notebook for human verification:

- `notebooks/progress.ipynb`

When a task changes runnable behavior, parser behavior, contracts, or artifact generation, Codex must also create or update `notebooks/progress.ipynb`.

The notebook must be executable top-to-bottom and must contain, in order:
1. a markdown title cell with the current phase and purpose
2. an environment/setup cell
3. an imports cell
4. a configuration cell for fixture paths / artifact root
5. one or more smoke-test execution cells that exercise the current implementation
6. a results-inspection cell that prints or displays the most important outputs
7. a short markdown notes cell describing known limitations or blockers

## Notebook rules

- Use the fixed path `notebooks/progress.ipynb`
- Update the notebook whenever implementation changes would affect manual testing
- Prefer deterministic cells and stable printed output
- Do not leave broken cells
- Do not leave placeholder cells claiming functionality that does not exist
- If notebook execution depends on local system prerequisites, document them in the first markdown cell
- Keep notebook outputs lightweight unless outputs themselves are the artifact under review

## Runtime requirements

For non-trivial work, Codex must use the sequential-thinking MCP server.

For any latest/current/external/platform-sensitive claim, Codex must use web search and cite authoritative sources.

If either required capability is unavailable:
- stop
- report the blocker verbatim
- do not continue with partial implementation

## Delivery footer required

Every substantive response must state:
- Sequential-thinking: used / blocked / not required
- Web search: used / blocked / not required
- Validation run: yes / no
- Blockers:
- Residual risks:


## Mandatory raw diff input

For every major change, Codex must include a raw diff excerpt derived from the actual repository diff, filtered to ignore paths matched by:

- `.diffignore`

The `.diffignore` file is a repo-root control file for change-log diff filtering.

Rules for `.diffignore`:
- fixed path: `.diffignore`
- one pattern per line
- blank lines are ignored
- lines starting with `#` are comments
- patterns must be interpreted using gitignore-style path matching relative to repo root

If `.diffignore` is present, any file matching it must be excluded from raw diff capture in `CHANGE_DIFF.md`.

If `.diffignore` is absent, raw diff capture must use the full repository diff.

## Change-diff requirements

For every major change, Codex must append a new dated entry to `CHANGE_DIFF.md` containing:
1. phase / task name
2. summary of what changed
3. affected files
4. user-visible or contract-visible impact
5. a concise diff-style summary of the essential changes
6. a raw diff section generated from the actual repo diff, excluding files matched by `.diffignore`
7. required migration, rollback, or re-run steps, if any

## Raw diff rules

- Use the fixed path `CHANGE_DIFF.md`
- The raw diff must be taken from the real repository state, not hand-written pseudo-diff
- The raw diff must exclude files matched by `.diffignore`
- Use fenced `diff` blocks
- Include only the highest-signal hunks, but they must remain verbatim excerpts from the real diff
- Do not include generated files, lockfile churn, notebook output noise, or vendor artifacts if they are ignored by `.diffignore`
- If a major change occurred and the filtered raw diff was not added, the task is incomplete
