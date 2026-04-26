## Workflow Orchestration

### 0. Your code will be reviewed with google gemini antigravity and claude code, so stop being lazy.

### 1. Plan Node Default

* Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions).
* If something goes sideways, STOP and re-plan immediately—don't keep pushing.
* Use plan mode for verification steps, not just building.
* Write detailed specs upfront to reduce ambiguity.

### 2. Subagent Strategy

* Use subagents liberally to keep main context window clean.
* Offload research, exploration, and parallel analysis to subagents.
* For complex problems, throw more compute at it via subagents.
* One **task** per subagent for focused execution.

### 3. Self-Improvement Loop

* After ANY correction from the user: update `tasks/lessons.md` with the pattern.
* Write rules for yourself that prevent the same mistake.
* Ruthlessly iterate on these lessons until mistake rate drops.
* Review lessons at session start for relevant project.

### 4. Verification Before Done

* Never mark a task complete without proving it works.
* Diff behavior between main and your changes when relevant.
* Ask yourself: "Would a staff engineer approve this?"
* Run tests, check logs, demonstrate correctness.

### 5. Demand Elegance (Balanced)

* For non-trivial changes: pause and ask "is there a more elegant way?"
* If a fix feels hacky: "Knowing everything I know now, implement the elegant solution."
* Skip this for simple, obvious fixes—don't over-engineer.
* Challenge your own work before presenting it.

### 6. Autonomous Bug Fixing

* When given a bug report: just fix it. Don't ask for hand-holding.
* Point at logs, errors, failing tests—then resolve them.
* Zero context switching required from the user.
* Go fix failing CI tests without being told how.

---

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items.
2. **Verify Plan**: Check in before starting implementation.
3. **Track Progress**: Mark items complete as you go.
4. **Explain Changes**: High-level summary at each step.
5. **Document Results**: Add review section to `tasks/todo.md`.
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections.

---

## Core Principles

* **Simplicity First**: Make every change as simple as possible. Impact minimal code.
* **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
* **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## Plan mode

For any non-trivial task, start in Plan mode before making changes.

A task is non-trivial if it includes any of the following:
- architecture or design decisions
- multi-file edits
- debugging without an already-proven root cause
- refactors, migrations, or dependency changes
- security, auth, data, infra, or performance-sensitive work
- ambiguous requirements or missing acceptance criteria
- any change that can break contracts, tests, or production behavior

### Required behavior in Plan mode

1. Gather context first.
   Read the relevant code paths, tests, configs, docs, and this `AGENTS.md` before proposing implementation.

2. Do not start editing immediately.
   First produce a concrete implementation plan unless the user explicitly requests a tiny, obvious change.

3. Resolve ambiguity early.
   If requirements are unclear, ask targeted clarification questions.
   If clarification is not possible, state explicit assumptions and keep them minimal.

4. Keep the plan implementation-grade.
   The plan must be specific enough that another engineer could execute it without guessing.

5. Optimize for correctness over speed.
   Prefer a smaller, safer plan with clear validation over a broad speculative rewrite.

### Plan output format

When in Plan mode, produce the plan with these sections:

- Objective
- Current state
- Constraints and non-goals
- Assumptions
- Risks / failure modes
- Files and systems affected
- Step-by-step implementation sequence
- Validation plan
- Rollback / recovery plan

### Plan quality bar

A valid plan must:
- identify the real change surface
- preserve existing contracts unless a contract change is explicitly required
- list the exact validations to run
- call out migrations, backfills, or operational steps if needed
- mention security, performance, and compatibility impacts when relevant
- avoid vague steps such as "update code accordingly"

### Execution after planning

After presenting the plan:
- wait for approval when the task is high-risk, architectural, or potentially disruptive
- otherwise execute strictly against the approved plan
- if reality differs from the plan, stop, explain the delta, and re-plan before continuing

### When to use a written execution plan

For large refactors, cross-cutting changes, or work expected to take many steps, create and maintain a written execution plan in `PLANS.md` or another repo-standard planning file.

That execution plan must be:
- a living document
- updated when scope or assumptions change
- specific about sequencing, validation, and rollback
- sufficient for a new engineer to resume the task from the document alone

### Anti-patterns

Do not:
- jump into code before understanding the system
- hide uncertainty
- make broad edits without an explicit plan
- mix unrelated fixes into the same change
- introduce new dependencies without justification
- skip validation because the change "looks small"

### Default rule

If there is any reasonable doubt about scope, impact, or approach, use Plan mode first.

## Dependency intelligence gate

Any plan that introduces, upgrades, downgrades, replaces, or relies on a package, SDK, framework, plugin, model client, build tool, linter, formatter, test tool, or infrastructure library MUST complete this gate before implementation.

No dependency change is allowed without explicit version validation and changelog review.

### Required pre-install / pre-upgrade workflow

1. Identify the exact dependency decision.
   Record:
   - package name
   - ecosystem / package manager
   - current repo version or state
   - proposed version
   - why the dependency is needed
   - whether it is production, build-time, dev-only, or test-only

2. Validate the latest stable version as of the current date.
   Codex must check authoritative sources, in this order:
   - official package registry entry
   - official upstream changelog / releases / release notes
   - official migration or upgrade guide
   - official deprecation notices
   - official security advisories, if available

3. Fetch the changelog window for the exact package being considered.
   Review all relevant release notes from the proposed version up to the current latest stable version.
   If proposing the latest stable version, still review:
   - the release notes for that version
   - the current major-version migration guide
   - any current deprecation / removal notices
   - runtime support policy changes

4. Extract decision-critical findings.
   Codex must explicitly identify:
   - breaking changes
   - deprecated APIs / flags / config patterns
   - removals and renamed symbols
   - runtime version support changes
   - peer dependency / transitive dependency constraints
   - packaging / install changes
   - security fixes or open advisories
   - operational concerns: startup behavior, warnings, telemetry, config drift, build impact

5. Choose the version deliberately.
   Default policy:
   - prefer the latest stable non-prerelease release
   - do not use `latest`, `*`, open-ended major ranges, or floating production versions
   - do not select an older version unless there is a documented compatibility reason
   - if not choosing the latest stable version, explain exactly why the latest stable version is rejected

6. Validate compatibility before coding.
   Codex must verify:
   - language runtime compatibility
   - framework compatibility
   - OS / architecture constraints if relevant
   - lockfile / resolver compatibility
   - compatibility with existing pinned dependencies
   - absence of known deprecation paths that would produce warnings in intended usage
   - absence of known critical/high security issues without an explicit mitigation plan

7. Reflect the dependency decision in the plan.
   Any plan involving dependency work must include a dedicated "Dependency review" subsection before implementation begins.

### Mandatory output format for every dependency decision

Dependency review
- Dependency:
- Ecosystem / package manager:
- Current repo version/state:
- Proposed version:
- Latest stable version as of review date:
- Review date:
- Authoritative sources checked:
- Changelog window reviewed:
- Breaking changes found:
- Deprecations found:
- Security advisories found:
- Runtime / platform compatibility:
- Peer / transitive dependency impact:
- Why this version was chosen:
- Why newer versions were not chosen:
- Residual risks:

### Failure policy

If Codex cannot verify latest-version status from authoritative sources, it must say so explicitly and must NOT claim that a version is current.

Required wording pattern:
- "Latest-version validation: blocked" or
- "Latest-version validation: verified"

If blocked:
- do not state or imply that the selected version is the latest
- do not present changelog coverage as complete
- do not add the dependency unless the task is explicitly constrained to local-only work
- mark the plan as incomplete and list the unresolved version / changelog risk

### Plan mode integration

When a task touches dependencies, Plan mode is mandatory.

The plan must include:
- dependency alternatives considered
- exact selected version
- latest stable version check
- changelog findings
- deprecation findings
- compatibility findings
- rollback path if the upgrade fails

No implementation may begin until this dependency review is complete.

### Anti-patterns

Do not:
- add packages without checking the latest stable release
- trust blog posts, copied snippets, or README examples as the only source of truth
- ignore migration guides
- ignore deprecation notices because "tests pass"
- use stale examples without version verification
- hide unresolved dependency uncertainty
- introduce a dependency when the standard library or existing stack already solves the problem acceptably

---

# IMPORTANT

YOU "MUST" FOLLOW THESE THINGS

THIS IS A VECTORLESS RAG FRAMEWORK!

I won't accept patch work, I need permanent enterprise production grade solution

I WON'T!!!

I WANT EVERYTHING RESEARCH BACKED, I WON'T TOLERATE A SINGLE DEPRECATION WARNING.