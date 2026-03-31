# CLAUDE.md

## Your code will be reviewed with google gemini antigravity and openai codex, so stop being lazy.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

NullVector is a **vectorless hierarchical RAG framework** — a CPU-first, deterministic document processing pipeline that builds auditable hierarchical trees from PDFs and Markdown without vector embeddings. All retrieval is structural (BM25-style ranking, Jaccard similarity, tree traversal) with full spatial traceability back to source bounding boxes.

## Commands

```bash
make setup          # uv sync --extra dev
make ci             # format-check + lint + typecheck + test (the full quality gate)
make format         # uv run ruff format src tests
make lint           # uv run ruff check src tests
make typecheck      # uv run mypy src tests
make test           # uv run pytest

# Single test
uv run pytest tests/unit/test_domain_models.py::test_name

# Run progress notebook (canonical manual verification)
uv run python scripts/run_progress_notebook.py

# Quickstart smoke test
uv run python scripts/nullvector_quickstart.py --source-path fixtures/pdfs/phase01/born_digital_with_outline.pdf
```

Pytest enforces `filterwarnings = ["error::DeprecationWarning"]` — deprecation warnings are test failures.

## Architecture

### Pipeline Flow

```
AcquisitionRequest
  → [ingest/acquisition_service] deterministic PDF/Markdown extraction
CanonicalDocumentLedger (text substrate, outlines, pages, bounding boxes)
  → [ingest/projection] transform into tree input
TreeSynthesisView
  → [tree/service] hierarchy assembly, verification, optional LLM repair
HierarchyNode tree (verified, with page anchors and summaries)
  → [retrieval/build] corpus construction from tree nodes
RetrievalCorpus (queryable units)
  → [retrieval/service] query planning, tree search, ranking
RetrievalHit[] with spatial citations
```

### Subsystems

- **domain/** — Authoritative Pydantic v2 type contracts. All models inherit `NullVectorModel` (`frozen=True`, `strict=True`, `extra="forbid"`). This is the source of truth for every data shape in the system.
- **ingest/** — Deterministic document acquisition. Providers: `native_pymupdf` (PDF), `markdown_native` (Markdown). CPU-first, no network. OCR is local Tesseract fallback only.
- **tree/** — Hierarchy assembly from headings, outlines, and TOC. Strategies: outline-only, TOC-derived, inferred-deterministic. Optional LLM-assisted verification and repair. `service.py` is the main orchestrator (~1100 lines).
- **llm/** — Structured LLM gateway with owned retries, schema-constrained output, and per-request audit. Protocol-driven: `ProviderAdapter` (provider boundary) and `StructuredLLMGateway` (public API). Adapters: OpenAI, LiteLLM.
- **semantic/** — Node summarization (bottom-up, LLM-backed or passthrough) and large-leaf decomposition.
- **retrieval/** — Query planning, tree-based search, BM25-style ranking, metadata/description selection. Indices: `InMemoryRetrievalIndex` (filesystem), `PostgresRetrievalIndex` (Postgres).
- **storage/** — `DocumentStore` protocol with filesystem and PostgreSQL backends. Run-scoped artifact persistence. `RunScopedStore` scopes all writes to a single reserved run.
- **observability/** — Structured JSONL logging, `log_event()` helper, Rich progress subscriber.
- **export/** — LangChain and LlamaIndex integration adapters.

### Storage Protocol

`DocumentStore` is the single persistence boundary. Two implementations: `FilesystemDocumentStore` and `PostgresDocumentStore`. The protocol provides run reservation, artifact read/write (JSON, JSONL, text, binary), retrieval unit persistence, metadata records, and audit/event logging. Factory: `build_document_store()` in `storage/factory.py`.

### Public API

The package exports ~100 domain types plus two batch orchestration functions:
- `acquire_batch()` — parallel document acquisition
- `build_tree_batch()` — parallel tree construction

Both use `ThreadPoolExecutor` internally and return `BatchResult[T]` with `successful` and `failed` tuples.

## Critical Constraints

- **Vectorless**: No vector embeddings anywhere. Retrieval is structural/lexical.
- **Deterministic-first**: LLM is fallback, not default. Parse path (Phase 01/02) is CPU-only.
- **Strict versioning**: `PyMuPDF==1.27.2`, `pypdf==6.8.0` — pinned, not ranges.
- **Zero deprecation warnings**: pytest treats `DeprecationWarning` as error.
- **Immutable artifacts**: All domain models are frozen. Run-scoped artifacts are write-once.
- **Schema-constrained LLM output**: Every model response is validated into typed Pydantic models. No regex-based JSON cleanup.
- **No network in parse path**: Acquisition is CPU-first. OCR uses local Tesseract only.

## Domain Model Rules

- All models inherit `NullVectorModel` from `domain/common.py`
- `tuple` over `list` for all sequence fields (immutability)
- `NonEmptyStr` (not bare `str`) for validated string fields
- `Field(default_factory=tuple)` for empty sequence defaults
- Enums via `StrEnum` for all categorical state
- Cross-field validation via `model_validator(mode="after")`

## LLM Gateway Rules

- All calls go through `StructuredLLMGateway` protocol — never call providers directly
- Retries are owned by NullVector (not delegated to provider SDKs)
- `GatewayRetryPolicy`: max_attempts=3, exponential backoff
- Retryable: TIMEOUT, RATE_LIMIT, NETWORK_FAILURE, UNKNOWN_PROVIDER_FAILURE
- Non-retryable: AUTH_FAILURE, VALIDATION_FAILURE, CONTEXT_LENGTH_VIOLATION, PROVIDER_REFUSAL
- Every invocation produces a `GatewayAuditRecord`

## Testing

- `tests/unit/` — domain models, parser, verification, gateway, adapters
- `tests/integration/` — full pipeline with real filesystem
- `tests/retrieval/` — planner, ranker, corpus builder, QA, tree search
- `tests/llm/` — gateway adapter tests
- `tests/corpus/` — large document corpus tests
- Markers: `@pytest.mark.integration`, `@pytest.mark.slow`

## Dependency Management

Use `uv` exclusively. Any new dependency requires the dependency intelligence gate:
1. Verify latest stable version from authoritative sources (PyPI, changelogs, migration guides)
2. Review breaking changes, deprecations, security advisories
3. Validate compatibility with Python >=3.11 and existing pinned deps
4. Document the review in the plan before implementation begins

## Workflow

- Plan mode for any non-trivial task (3+ steps or architectural decisions)
- Track progress in `tasks/todo.md`, lessons in `tasks/lessons.md`
- Run `make ci` before considering any change complete
- After each phase, append filtered diff to `CHANGE_DIFF.md` (respecting `.diffignore`)