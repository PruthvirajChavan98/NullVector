# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

NullVector is a **vectorless hierarchical RAG framework** — an LLM/VLM-driven document processing pipeline that builds auditable hierarchical trees from PDFs and Markdown without vector embeddings. PDF pages are rendered to images and transcribed to Markdown via a VLM, then an LLM synthesizes the document hierarchy. All retrieval is structural (tree traversal, LLM-driven ranking) with traceability back to source pages.

This is a **Python library first** — no HTTP endpoints, no ASGI server. The CLI and async wrappers are thin adapters over the same synchronous library-owned runtime.

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

# Quickstart smoke test
uv run python scripts/nullvector_quickstart.py --source-path fixtures/pdfs/phase01/born_digital_with_outline.pdf

# Installed CLI (two entrypoints, identical)
uv run nullvector ingest document.pdf
uv run nv search "your query" --document-id <id>
```

Pytest enforces `filterwarnings = ["error::DeprecationWarning"]` — deprecation warnings are test failures. Ruff line-length is 100. Mypy runs in strict mode.

## Architecture

### Pipeline Flow

```
AcquisitionRequest
  -> [ingest/acquisition_service] PDF page rendering + VLM Markdown transcription
CanonicalDocumentLedger (VLM Markdown per page, outlines)
  -> [ingest/projection] transform into tree input
TreeSynthesisView
  -> [tree/service] LLM hierarchy synthesis (or outline-based fallback)
HierarchyNode tree (with page spans and summaries)
  -> [retrieval/build] corpus construction from tree nodes
RetrievalCorpus (queryable units)
  -> [retrieval/service] query planning, tree search, ranking
RetrievalHit[] with page citations
```

### Subsystems

- **domain/** — Authoritative Pydantic v2 type contracts. All models inherit `NullVectorModel` (`frozen=True`, `strict=True`, `extra="forbid"`). Source of truth for every data shape.
- **ingest/** — VLM-driven document acquisition. `page_renderer.py` renders PDF pages to PNG, `vlm_transcriber.py` invokes a multimodal gateway for Markdown transcription. Providers: `native_pymupdf` (PDF with VLM or raw text fallback), `markdown_native` (Markdown). No OCR or font-size analysis.
- **tree/** — LLM-driven hierarchy synthesis. `llm_hierarchy.py` invokes the gateway for document structure, with outline-based fallback when no gateway is configured. `service.py` is the orchestrator (~340 lines).
- **llm/** — Structured LLM gateway with owned retries, schema-constrained output, and per-request audit. Protocol-driven: `ProviderAdapter` (provider boundary) and `StructuredLLMGateway` (public API). Adapters: OpenAI, LiteLLM, Noop. Prompt builders for VLM transcription, hierarchy synthesis, decomposition, summarization, tree search, and QA.
- **semantic/** — Node summarization (bottom-up, LLM-backed or passthrough) and large-leaf decomposition.
- **retrieval/** — Query planning, tree-based search, BM25-style ranking, metadata/description selection. Indices: `InMemoryRetrievalIndex` (filesystem), `PostgresRetrievalIndex` (Postgres). Includes QA response generation via `RetrievalQAService`.
- **storage/** — `DocumentStore` protocol with filesystem and PostgreSQL backends. Run-scoped artifact persistence via `RunScopedStore`. Factory: `build_document_store()` in `storage/factory.py`.
- **observability/** — Structured JSONL logging, `log_event()` helper, Rich progress subscriber.
- **export/** — LangChain and LlamaIndex bridge adapters (edge-only, thin type converters).

### Client Facade (`client.py`)

`NullVectorClient` is the high-level DX surface. It chains acquisition -> tree -> retrieval -> QA under a single workspace root. Key methods:

- `ingest(source_path)` — full pipeline: acquire + tree + retrieval in one call
- `acquire(source_path)` — acquisition only
- `build_tree(acquisition_manifest_path)` — tree from existing acquisition
- `build_retrieval(acquisition_manifest_path)` — retrieval corpus from existing acquisition
- `build_description(acquisition_manifest_path, tree_manifest_path)` — document-level description (LLM-backed)
- `search(query, document_id=...)` — structural retrieval hits
- `ask(query, document_id=...)` — LLM-grounded QA with citations

Every method has an `async_` variant (`async_ingest`, `async_search`, etc.) that wraps the sync method via `asyncio.to_thread`.

The client maintains a local catalog at `<workspace>/.nullvector/catalog.json` mapping document IDs to their latest artifact manifest paths.

### CLI (`cli.py`)

Installed as `nullvector` and `nv` via `pyproject.toml [project.scripts]`. Typer-based. Commands mirror the client facade: `ingest`, `build-tree`, `search`, `ask`. All output is JSON via `canonical_json_text`. Supports `--storage-backend=postgres` with `--pg-conninfo` and `--pg-schema`.

### Presets System (`presets.py`)

`DocumentPreset` bundles `AcquisitionSettings`, `TreeSettings`, `DocumentDescriptionSettings`, and `tree_summarize` flag. Currently one built-in preset: `"general_document"`. Client methods accept `preset: str | DocumentPreset | None`.

### Protocol Boundaries

All inter-layer contracts are `typing.Protocol` classes:

| Protocol | Module | Purpose |
|----------|--------|---------|
| `DocumentStore` | `storage/protocol.py` | Persistence read/write boundary |
| `RunScopedStore` | `storage/protocol.py` | Single-run persistence handle |
| `StructuredLLMGateway` | `llm/protocols.py` | Typed LLM invocation |
| `ProviderAdapter` | `llm/protocols.py` | Internal provider transport |
| `RepairEngine` | `tree/repair.py` | Tree repair strategy |
| `AcquisitionProvider` | `ingest/protocols.py` | Document extraction |

Async mirrors exist for `DocumentStore`, `RunScopedStore`, `StructuredLLMGateway`, and `ProviderAdapter`.

### Storage Dual-Backend

`DocumentStore` protocol has two implementations:

- **`FilesystemDocumentStore`** — default, zero-dependency. Artifacts written to `<workspace>/artifacts/<run_type>_runs/<run_id>/<document_id>/`.
- **`PostgresDocumentStore`** — optional, requires `psycopg` (`uv sync --extra postgres`). Artifacts referenced via `pg://<run_type>/<run_id>/<document_id>/<artifact_path>`.

Artifact refs are strings. Filesystem refs are plain paths; Postgres refs start with `pg://`. The `is_postgres_ref()` helper in `storage/_serialization.py` detects the backend from a ref string. `load_model_artifact()` in `_client_utils.py` loads from either backend transparently.

### Error Hierarchy

```
NullVectorError (base)
+-- ClientValidationError   — bad user inputs or preset configuration
+-- IngestionError          — document acquisition failure
+-- TreeBuildError          — tree synthesis failure
+-- RetrievalError          — retrieval/description artifact failure
+-- QueryError              — search or QA execution failure
    +-- GatewayInvocationError   — single LLM call failure
    +-- GatewayUnavailableError  — gateway circuit open or misconfigured
    +-- DocumentNotIndexedError  — document not in catalog
```

`translate_error()` in `errors.py` converts internal exceptions into this public hierarchy. All client/CLI code catches broadly and translates via this function.

### Run-ID System

Every pipeline stage produces a unique run identified by a run ID. Auto-generated IDs follow the pattern `<stem>-<12-hex-token>-<stage>` (e.g., `my-document-a1b2c3d4e5f6-acquisition`). Derived stages strip the current stage suffix and append the target stage, preserving the token for traceability across acquisition -> tree -> retrieval chains. See `_client_utils.py`.

### Batch Orchestration

`acquire_batch()` and `build_tree_batch()` (plus async variants) use `ThreadPoolExecutor` internally and return `BatchResult[T]` with `successful` and `failed` tuples.

## Critical Constraints

- **Vectorless**: No vector embeddings anywhere. Retrieval is structural/LLM-driven.
- **LLM-first**: VLM transcribes pages, LLM synthesizes hierarchy. Outline-based fallback when no gateway configured.
- **Strict versioning**: `PyMuPDF==1.27.2` — pinned exact for page rendering.
- **Zero deprecation warnings**: pytest treats `DeprecationWarning` as error.
- **Immutable artifacts**: All domain models are frozen. Run-scoped artifacts are write-once.
- **Schema-constrained LLM output**: Every LLM response is validated into typed Pydantic models. No regex-based JSON cleanup.
- **VLM for acquisition**: PDF pages rendered to PNG, transcribed to Markdown via multimodal gateway. No OCR or font-size analysis.
- **tuple over list**: All sequence fields in domain models use `tuple`, never `list`.
- **NonEmptyStr over str**: Validated string fields use the `NonEmptyStr` annotated type.

## Domain Model Rules

- All models inherit `NullVectorModel` from `domain/common.py`
- `tuple` over `list` for all sequence fields (immutability)
- `NonEmptyStr` (not bare `str`) for validated string fields
- `Field(default_factory=tuple)` for empty sequence defaults
- Enums via `StrEnum` for all categorical state
- Cross-field validation via `model_validator(mode="after")`
- `CoerceTuple` (`BeforeValidator`) handles JSON list->tuple deserialization

## LLM Gateway Rules

- All calls go through `StructuredLLMGateway` protocol — never call providers directly
- Retries are owned by NullVector (not delegated to provider SDKs)
- `GatewayRetryPolicy`: max_attempts=3, exponential backoff
- Retryable: TIMEOUT, RATE_LIMIT, NETWORK_FAILURE, UNKNOWN_PROVIDER_FAILURE
- Non-retryable: AUTH_FAILURE, VALIDATION_FAILURE, CONTEXT_LENGTH_VIOLATION, PROVIDER_REFUSAL
- Every invocation produces a `GatewayAuditRecord`
- The gateway uses typed failure envelopes (`GatewaySuccess | GatewayFailure`) for expected failures, not exceptions
- VLM transcription and hierarchy synthesis are gateway operations with typed response models (`VLMTranscriptionResponse`, `HierarchySynthesisResponse`)

## Testing

- `tests/unit/` — domain models, parser, verification, gateway, adapters, client utils, presets
- `tests/integration/` — full pipeline with real filesystem, client facade, CLI commands
- `tests/retrieval/` — planner, ranker, corpus builder, QA, tree search, description selection
- Markers: `@pytest.mark.integration`, `@pytest.mark.slow`, `@pytest.mark.asyncio`
- `asyncio_mode = "auto"` in pytest config — async tests are auto-detected

## Dependency Management

Use `uv` exclusively. Optional extras: `dev` (testing/linting), `postgres` (psycopg). Any new dependency requires:
1. Verify latest stable version from authoritative sources (PyPI, changelogs)
2. Review breaking changes, deprecations, security advisories
3. Validate compatibility with Python >=3.11 and existing pinned deps

## Workflow

- Plan mode for any non-trivial task (3+ steps or architectural decisions)
- Track progress in `tasks/todo.md`, lessons in `tasks/lessons.md`
- Run `make ci` before considering any change complete
- Reference `docs/architecture.md` for detailed module-level documentation
- ADRs in `docs/adr/` are the authoritative record of architectural decisions
