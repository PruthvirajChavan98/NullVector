# Codex Runtime Enforcement — StrataForge

This repository requires Codex to use:
1. the sequential-thinking MCP server for non-trivial reasoning
2. web search for any claim that may depend on current, external, or niche information

These rules are mandatory.

## Mandatory preflight
Before starting any substantive task, Codex must run:

    bash .codex/bin/preflight-codex.sh

If preflight fails:
- stop immediately
- do not continue with partial implementation
- report the exact missing capability
- report the exact command output
- mark the task blocked

## Sequential-thinking MCP policy
Codex must use the sequential-thinking MCP server when any of the following is true:
- the task is architectural
- the task requires multi-step design or trade-off analysis
- the task involves phased planning
- the task spans multiple files or subsystems
- the task contains ambiguity that requires explicit decomposition
- the task requests enterprise-grade or production-grade design

Sequential-thinking is not optional for these cases.

Codex must:
- decompose the task first
- record assumptions explicitly
- evaluate alternatives before choosing one
- produce a short execution plan before editing code
- revisit the plan if a blocker appears

If the sequential-thinking MCP server is unavailable, Codex must stop and report:
- "BLOCKED: sequential-thinking MCP server is required by repository policy"

## Web-search policy
Codex must perform web search before responding whenever any of the following is true:
- the task asks for latest, current, recent, new, updated, today, now, or similar
- the task involves vendor docs, APIs, SDKs, libraries, tools, frameworks, models, pricing, limits, or release status
- the task involves OpenAI, Codex, MCP, model capabilities, or platform features
- the task involves security guidance, compliance guidance, or operational guidance
- the task includes a term, package, or feature name that may have changed
- the task would benefit from direct citations
- there is any non-trivial chance the information is stale

Web search is mandatory in those cases.
If web search is unavailable, Codex must stop and report:
- "BLOCKED: web search is required by repository policy"

## Citation policy
When web search is used:
- cite the most load-bearing claims
- prefer official docs, vendor docs, specs, or primary sources
- distinguish verified facts from design recommendations
- do not present guessed configuration as fact

## Implementation policy
Codex must not:
- invent MCP configuration syntax it has not verified
- invent package names it has not verified
- claim a platform feature exists unless verified by current docs
- continue after a required runtime capability is missing

## Delivery policy
Every substantive response must include:
1. whether sequential-thinking was used
2. whether web search was used
3. blockers, if any
4. residual risks, if any

