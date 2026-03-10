# StrataForge — Repository Operating Contract

StrataForge is a CPU-first, enterprise-grade document hierarchy framework for ingesting massive technical PDFs into a verifiable hierarchical JSON tree.

## Mission
Build a production-grade ingestion and hierarchy system for 10,000+ page PDFs with:
- deterministic parsing first
- OCR fallback second
- bounded LLM usage third
- strict typed contracts everywhere
- zero deprecation warnings in CI
- full provenance, replayability, and observability

## Scope
In scope:
- document intake
- native PDF parsing
- OCR fallback
- hierarchy synthesis
- summary generation
- verification loops
- typed LLM gateway
- workflow orchestration
- storage, APIs, and MCP exposure
- observability and release hardening

Explicitly out of scope for now:
- retrieval architecture
- vector search
- agentic query traversal
- answer generation pipelines

## Global rules
1. Never bypass typed contracts.
2. Never parse LLM JSON with regex hacks.
3. Never let the API event loop perform CPU-bound PDF/OCR work directly.
4. Never introduce synchronous DB calls inside async request handlers.
5. Never commit a model-facing schema without a corresponding runtime validator.
6. Never ship code with deprecation warnings, implicit anys, or silent fallbacks.
7. Every persisted hierarchy node must be traceable to page ranges and source anchors.
8. Every repair step must be logged and diffable.
9. Every workflow step must be idempotent.
10. Every phase ends with tests, docs, and explicit acceptance evidence.

## Non-negotiable engineering constraints
- CPU-only deployment target
- Python 3.11+
- strict typing
- reproducible local dev
- deterministic tests where possible
- bounded concurrency
- structured logs
- OpenTelemetry instrumentation
- no hidden network dependency in core parse path

## Architecture defaults
- API: FastAPI
- DB access: asyncpg or SQLAlchemy async only
- workflow/orchestration: LangGraph for local state graphs, Temporal-class durability for long-running production execution
- PDF parsing: PyMuPDF + pypdf
- OCR fallback: Tesseract
- typed models: Pydantic v2
- LLM gateway: provider adapter + JSON Schema structured outputs + Pydantic validation
- streaming: SSE
- tracing: OpenTelemetry

## Required repository artifacts
- docs/adr/ for architecture decisions
- .codex/rules/ for execution rules
- .codex/prompts/ for phase-scoped Codex tasks
- tests/ for unit, integration, and corpus-based regression tests
- fixtures/ for representative PDFs
- schemas/ or app-domain models for authoritative contracts

## Mandatory delivery contract for every Codex task
When implementing a task:
1. restate the exact files you changed
2. explain why those files changed
3. run the required validation commands
4. report failures verbatim
5. report residual risks
6. do not claim success unless tests actually passed

## Required validations before claiming completion
At minimum, run the project-equivalent of:
- format
- lint
- type-check
- unit tests
- targeted integration tests

If a phase prompt defines stricter checks, those stricter checks win.

## Change discipline
- Keep patches small and phase-aligned.
- Do not mix architecture refactors with feature work unless the prompt explicitly requires both.
- Prefer additive migrations over destructive rewrites unless explicitly authorized.
- Preserve backwards compatibility inside the phase unless the phase is explicitly a breaking migration.

## ADR discipline
Any non-trivial choice must create or update an ADR:
- workflow engine choice
- DB schema changes
- OCR strategy changes
- LLM schema changes
- retry/backoff policy changes
- storage layout changes
- security boundary changes

## Failure handling
If blocked:
- do not hand-wave
- do not silently skip validation
- do not suppress stack traces
- return the exact blocker, current state, and smallest safe next step

## Mandatory repo context

Before planning or editing code for StrataForge:
- Read everything from `.codex/'