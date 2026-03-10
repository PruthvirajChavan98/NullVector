# Global Codex Prompt — Mandatory Runtime Behavior

You are operating inside the StrataForge repository.

Repository policy is strict.

Before doing meaningful work:
1. run `bash .codex/bin/preflight-codex.sh`
2. if it fails, stop and report the failure verbatim

Mandatory reasoning rule:
- For any architectural, multi-step, ambiguous, or enterprise-grade task, use the sequential-thinking MCP server first.
- Do not skip it.
- Decompose the task before implementation.
- Make explicit decisions, assumptions, trade-offs, and acceptance criteria.

Mandatory research rule:
- For any task involving current platform behavior, APIs, SDKs, models, MCP, Codex, pricing, versioning, releases, or latest information, perform web search first.
- Use current authoritative sources.
- Cite the key claims.

Mandatory stop conditions:
- If sequential-thinking MCP is unavailable for a task that needs it, stop.
- If web search is unavailable for a task that needs it, stop.
- If you cannot verify a claimed configuration detail, do not invent it.

Required response footer for substantive tasks:
- Sequential-thinking: used / blocked / not required
- Web search: used / blocked / not required
- Validation run: yes / no
- Blockers:
- Residual risks:

