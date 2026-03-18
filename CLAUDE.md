# NullVector

# IMPORTANT:
I won't accept patch work, i need permanent enterprise production grade solution

I WON'T!!!

I WANT EVERYTHING RESEARCH BACKED, I WON'T TOLERATE A SINGLE DEPRECATION WARNING

You should proactively search when you encounter things like:

Version pins that might be outdated
API signatures you are uncertain about (deprecations)
New library features before recommending them

---

> **Onboarding brief for Claude Code.** Loaded at session start.
> Keep sessions focused: `/clear` between unrelated tasks. Reference `@docs/` on demand.

---

## 1. Project Identity

| Key             | Value                                                                |
|-----------------|----------------------------------------------------------------------|
| **What**        | CPU-first document hierarchy framework for deterministic PDF ingestion |
| **Type**        | Python library (no web framework, no HTTP endpoints)                 |
| **Python**      | `>=3.11` (enforced via `pyproject.toml`)                             |
| **Package mgr** | `uv` (NOT pip, NOT poetry)                                          |
| **Build**       | `hatchling>=1.27.0` (PEP 517 src layout)                            |
| **Test runner** | `pytest` with `--strict-config --strict-markers`                     |
| **Lint / fmt**  | `ruff 0.11.x` (linting + formatting)                                |
| **Type check**  | `mypy --strict`                                                      |
| **CI**          | None configured yet. Quality gate is local via `make ci`.            |

---

## 2. Repository Layout

```
.
├── src/nullvector/              # All importable source code (PEP 517 src layout)
│   ├── domain/                  # Authoritative Pydantic contracts (StrataModel base)
│   │   ├── common.py            # Geometry, spans, coordinate spaces
│   │   ├── ledger.py            # Parse manifests, canonical ledger (v2)
│   │   ├── tree.py              # Hierarchy nodes, tree synthesis, repair
│   │   ├── events.py            # DocumentEvent, PageEvent, provenance
│   │   ├── gateway.py           # LLM gateway response types
│   │   └── retrieval.py         # Retrieval corpus, hits, evidence
│   ├── ingest/                  # Phase 01: PDF acquisition & parsing
│   │   ├── acquisition_service.py  # V2 acquisition runtime (uses DocumentStore)
│   │   ├── service.py           # Legacy parse service
│   │   ├── providers/           # PyMuPDF provider implementation
│   │   └── protocols.py         # AcquisitionProvider, TranslationAdapter
│   ├── tree/                    # Phase 02: Deterministic hierarchy builder
│   │   ├── service.py           # TreePipelineService
│   │   ├── strategy.py          # Hierarchy strategy selection
│   │   ├── headings.py          # Heading extraction & scoring
│   │   ├── hierarchy.py         # Hierarchy synthesis
│   │   ├── repair.py            # RepairEngine protocol + NoopRepairEngine
│   │   ├── verify.py            # Tree verification
│   │   ├── toc.py / toc_reconcile.py  # TOC extraction & reconciliation
│   │   └── anchors.py           # Line anchoring
│   ├── llm/                     # Phase 03: Typed LLM gateway
│   │   ├── service.py           # GatewayService (sync-first, retries, auditing)
│   │   ├── protocols.py         # ProviderAdapter, StructuredLLMGateway
│   │   ├── adapters/            # Optional convenience adapters (OpenAI, LiteLLM) — zero deps
│   │   ├── providers/           # Noop adapter (users bring their own ProviderAdapter)
│   │   ├── prompts/             # Prompt templates (repair, summarization, verification, toc)
│   │   └── types.py             # GatewayRequest, GatewaySuccess, GatewayFailure
│   ├── retrieval/               # Corpus building, query planning, ranking, QA
│   │   ├── service.py           # RetrievalService
│   │   ├── build.py             # RetrievalCorpusBuilder
│   │   ├── planner.py           # QueryPlanner
│   │   ├── rank.py              # RetrievalRanker
│   │   ├── index.py             # In-memory & PostgreSQL indices
│   │   └── qa.py                # QA response generation
│   ├── semantic/                # Decomposition & summarization
│   │   ├── decompose.py         # NodeDecomposer
│   │   ├── summarize.py         # NodeSummarizer
│   │   └── tokens.py            # Tokenizer protocol & heuristics
│   ├── storage/                 # Backend-agnostic persistence (NEW)
│   │   ├── protocol.py          # DocumentStore, RunScopedStore protocols
│   │   ├── filesystem.py        # FilesystemDocumentStore
│   │   ├── postgres.py          # PostgresDocumentStore (optional)
│   │   ├── factory.py           # build_document_store()
│   │   └── config.py            # StorageConfig types
│   ├── observability/           # Structured logging & subscribers
│   │   ├── logging.py           # log_event() + typed event helpers
│   │   └── subscribers/         # JSONL logger, Rich progress bars
│   ├── export/                  # Edge-only bridges (LangChain, LlamaIndex)
│   └── constants.py             # Version locks, paths
│
├── tests/
│   ├── unit/                    # Pure logic tests (no real I/O)
│   ├── integration/             # Real infrastructure tests
│   ├── retrieval/               # Retrieval-specific tests
│   └── llm/                     # LLM adapter tests
│
├── docs/
│   ├── architecture.md          # !! STALE — describes phantom FastAPI/SQLAlchemy app !!
│   ├── coding-standards.md      # !! STALE — references phantom dependencies !!
│   ├── development-workflows.md # !! STALE — references phantom CI/pre-commit !!
│   └── adr/                     # Architecture Decision Records (0000-0008) — ACCURATE
│
├── fixtures/                    # Golden test expectations (phase01, phase02)
├── notebooks/                   # Development notebooks
├── cookbook/                     # Example job runs and usage
├── pyproject.toml               # Single source of truth for all tool config
└── Makefile                     # uv command wrappers
```

---

## 3. Dependencies (Actual)

### Production
| Package | Pin | Purpose |
|---------|-----|---------|
| `httpx` | `>=0.28.0,<1.0.0` | Async HTTP client |
| `PyMuPDF` | `==1.27.2` | Primary PDF parser (exact pin for determinism) |
| `pypdf` | `==6.8.0` | Alternative outline extractor (exact pin) |
| `pydantic` | `>=2.11.0,<3.0.0` | Domain model validation |

### Development (`[dev]` extra)
| Package | Purpose |
|---------|---------|
| `mypy` | Strict type checking |
| `pytest` | Test runner |
| `ruff` | Lint + format |
| `ipykernel`, `nbclient`, `nbformat` | Jupyter support |

### Optional (`[postgres]` extra)
| Package | Purpose |
|---------|---------|
| `psycopg[binary]` | PostgreSQL storage backend |

### Optional Convenience Adapters (zero new dependencies)
| Adapter | SDK Required | Install |
|---------|-------------|---------|
| `OpenAIAdapter` | `openai>=1.0.0` | `pip install openai` |
| `LiteLLMAdapter` | `litellm>=1.79.0` | `pip install litellm` |

### NOT in dependencies (despite docs claiming otherwise)
- `pytest-asyncio` — not installed
- `pytest-mock` — not installed
- `pydantic-settings` — not installed
- `FastAPI` — not used (pure library)
- `SQLAlchemy` — not used
- `Redis` — not used

---

## 4. Essential Commands

```bash
# Bootstrap
uv sync --extra dev

# Full quality gate (run before any commit)
make ci
# Equivalent to: ruff format --check + ruff check + mypy + pytest

# Individual tools
uv run ruff check --fix .         # Auto-fix lint
uv run ruff format .              # Format in-place
uv run mypy src/                  # Strict type check (src only)
uv run pytest -x -q               # Fast-fail tests
uv run pytest tests/unit/         # Unit tests only
uv run pytest tests/integration/  # Integration tests

# Dependency management
uv add <package>                  # Add production dep (requires human approval)
uv add --dev <package>            # Add dev dep (requires human approval)
uv lock                           # Regenerate lockfile
```

---

## 5. Non-Negotiable Constraints

### Python & Typing
- Python 3.11+. Use `str | None`, not `Optional[str]`.
- Every public function/method/class requires complete type annotations.
- `mypy --strict` must pass with zero errors. No `# type: ignore` without inline explanation.
- mypy ignores `fitz` (PyMuPDF) — it has no type stubs.

### Imports
- PEP 517 src layout. All imports are absolute: `from nullvector.domain.tree import HierarchyNode`.
- No relative imports except within the same sub-package.
- Never add dependencies without explicit human approval.

### Domain Models
- All domain types inherit from `NullVectorModel` (defined in `domain/common.py`): `frozen=True, extra="forbid", strict=True`.
- Use Pydantic v2 semantics only. No v1 compatibility shims.
- Constrained types: `NonEmptyStr`, `Sha256Hex`, `PositiveInt`, `NonNegativeInt` (defined in `domain/common.py`).

### Error Handling
- Domain-specific exceptions only. Defined in `ingest/errors.py`, `llm/errors.py`, `tree/service.py`, `storage/postgres.py`.
- Never swallow exceptions silently. Log before re-raising.
- Bare `except Exception:` only for documented defensive cases (see `outline.py`).

### Storage
- All persistence goes through `DocumentStore` protocol (`storage/protocol.py`).
- Services receive a `RunScopedStore` handle scoped to a single run.
- Two backends: `FilesystemDocumentStore` (default), `PostgresDocumentStore` (optional).

### Testing
- Unit tests: pure logic, no filesystem/network/database. Located in `tests/unit/`.
- Integration tests: real infrastructure. Located in `tests/integration/`.
- Test data in `fixtures/` with golden expectations for deterministic validation.
- `filterwarnings = ["error::DeprecationWarning"]` — deprecation warnings fail tests.

### Security
- No secrets or PII in source or tests. Use environment variables.
- Validate external input at provider/adapter boundaries.

---

## 6. Code Style

- **Docstrings**: Google style. Required on every public class and function.
- **Naming**: `snake_case` functions/variables, `PascalCase` classes, `UPPER_SNAKE` constants.
- **Line length**: 100 chars.
- **Ruff rules**: `B, E, F, I, PTH, RUF, SIM, UP, W` (configured in `pyproject.toml`).
- **No magic numbers**: Extract to named constants.
- **No `print()`**: Use `logging` module. Structured events via `observability/logging.py`.

---

## 7. Architecture Notes

### This is NOT a web app
NullVector is a **library** for deterministic PDF document ingestion and hierarchy building.
It has no HTTP endpoints, no CLI entry point, no ASGI server. It is meant to be imported
and used programmatically.

### Processing Phases
1. **Ingest** (`ingest/`): Acquire PDF, extract text/images, build canonical ledger
2. **Tree** (`tree/`): Build deterministic document hierarchy from headings, outlines, TOC
3. **LLM** (`llm/`): Optional enrichment via typed LLM gateway (repair, summarization, verification)
4. **Retrieval** (`retrieval/`): Build searchable corpus, plan queries, rank results
5. **Semantic** (`semantic/`): Node decomposition and summarization

### Key Design Patterns
- **Protocol-based boundaries**: `AcquisitionProvider`, `ProviderAdapter`, `DocumentStore`, `RepairEngine`
- **Typed failure envelopes**: `GatewaySuccess | GatewayFailure` instead of exceptions for expected failures
- **Deterministic outputs**: Exact version pins on PDF parsers, content-addressed fingerprinting
- **Artifact-driven pipelines**: Each phase produces typed artifacts persisted via `DocumentStore`
- **BYOLLM (Bring Your Own LLM)**: `provider_adapter` is a required kwarg on `GatewayService`.
  Users bring their own SDK client. Optional convenience adapters in `llm/adapters/` wrap
  OpenAI and LiteLLM with zero added dependencies (lazy imports).

### ADRs (Authoritative)
The `docs/adr/` directory contains the actual architectural decisions:
- ADR 0001-0003: Bootstrap, parser substrate, tree pipeline
- ADR 0004: LLM gateway design
- ADR 0005: Tree enhancements (TOC, strategy, decomposition)
- ADR 0006-0008: V2 ledger, acquisition runtime, major v2 changes

---

## 8. What Claude Should Always Do

- Run `uv run ruff check --fix .` after any code change.
- Run `uv run ruff format .` after any code change.
- Run `uv run mypy src/` to validate types on modified modules.
- Check existing patterns in `src/nullvector/` before introducing new abstractions.
- Read `docs/adr/` before making architectural changes.
- Prefer editing existing files over creating new ones.

## 9. What Claude Must Never Do

- Add, remove, or change dependencies without explicit human approval.
- Use `print()` — use `logging` or `observability/logging.py` helpers.
- Use deprecated stdlib APIs. Target Python 3.11 exclusively.
- Leave `# TODO` or `# FIXME` comments in committed code.
- Run destructive database commands without explicit instruction.
- Reference non-existent modules: `core/`, `adapters/`, `api/routers/`, `api/schemas/`.

---

## 10. Known Issues (Active)

> See `docs/audit-patchwork-overengineering.md` for the full analysis.

- **Half-migrated storage**: Old `ArtifactStore` classes coexist with new `DocumentStore` protocol.
- **Dead cookbook imports**: Notebooks reference deleted `multimodal_gateway` sub-package.
- **Missing dev deps**: `pytest-asyncio` and `pytest-mock` not in `pyproject.toml`.
- **No CI**: No GitHub Actions, no pre-commit hooks, no commitlint.
