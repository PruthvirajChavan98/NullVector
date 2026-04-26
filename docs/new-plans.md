# NullVector Architectural Refactoring Plan

## Context

NullVector is a vectorless RAG framework with a clean domain model layer but growing architectural debt in its service layers. The storage abstraction leaks backend-specific branching into business logic (18 occurrences across 10 non-storage files), concurrency uses heavyweight ThreadPoolExecutor instead of asyncio, Pydantic tuple coercion is duplicated across 10+ classes, god functions mix pure logic with side-effects, the gateway lacks resilience patterns, and there is no developer-friendly facade. This plan addresses all six workstreams in a dependency-aware sequence.

Current baseline: `make ci` passes. All unit and retrieval tests pass. `notebooks/progress.ipynb` executes cleanly.

## Phasing & Dependencies

```
Phase 0 (parallel):  WS3 (DRY Tuple Coercion) + WS5 (Gateway Resilience)
Phase 1:             WS1 (Storage Abstraction Leaks)
Phase 2:             WS4 (God Function Extraction)
Phase 3:             WS2 (Threads -> asyncio)
Phase 4:             WS6 (DX: Facade + CLI + Presets + Error Translation)
```

WS3 and WS5 touch disjoint files. WS1 must precede WS2/WS4 (they touch the same service files). WS2 depends on WS5 (circuit breaker should be async-ready). WS6 depends on all others (facade wraps the cleaned API).

---

## [x] Phase 0A: WS3 -- DRY Up Pydantic Tuple Coercion

### Objective
Eliminate ~80 lines of repetitive `_coerce_sequence_fields` validators by creating a reusable `CoerceTuple` `BeforeValidator` in `domain/common.py`.

### Files Modified
- `src/nullvector/domain/common.py` -- add `_coerce_tuple()` and `CoerceTuple`
- `src/nullvector/domain/tree.py` -- refactor 8 classes
- `src/nullvector/domain/retrieval.py` -- refactor `TreeSearchFrontierNode`
- `src/nullvector/domain/document_selection.py` -- partial refactor of `DocumentFilterClause` (keep operator coercion)
- `src/nullvector/domain/__init__.py` -- export `CoerceTuple`

### Implementation

**Step 1** -- Add to `domain/common.py`:
```python
from pydantic import BeforeValidator

def _coerce_tuple(v: object) -> object:
    """Coerce list->tuple for strict frozen models deserializing from JSON."""
    if isinstance(v, list):
        return tuple(v)
    return v

CoerceTuple = BeforeValidator(_coerce_tuple)
```

**Step 2** -- For each class, replace bare `tuple[X, ...]` fields that have a coercion validator with `Annotated[tuple[X, ...], CoerceTuple]`, then delete the validator method.

**Classes to refactor:**
| Class | File | Validator Lines | Fields |
|-------|------|----------------|--------|
| HierarchyNode | tree.py | 438-446 | path, owned_spans, source_anchors |
| NodeCard | tree.py | 524-532 | path, owned_spans, keywords, source_anchors |
| NodeSummary | tree.py | 579-587 | keywords |
| TreeNodeVerificationResult | tree.py | 701-709 | issues, notes |
| VerificationReport | tree.py | 734-748 | node_results, document_issues, unassigned_spans, notes |
| VerificationResult | tree.py | 774-782 | issues, notes |
| CompactedTreeNode | tree.py | 863-871 | path, child_serving_node_ids, canonical_node_ids |
| CompactedNodeMapping | tree.py | 890-898 | canonical_node_ids |
| TreeSearchFrontierNode | retrieval.py | 137-147 | path, keywords (currently model_validator -- replace entirely) |
| DocumentFilterClause | document_selection.py | 46-57 | value only (keep operator coercion in model_validator) |

### Validation
- `uv run pytest tests/unit/test_domain_models.py tests/unit/test_storage_serialization.py tests/unit/test_tree_pipeline_unit.py`
- `uv run mypy --strict src/nullvector/domain/`
- `uv run ruff check src/nullvector/domain/`
- Add unit tests: `CoerceTuple` converts list->tuple, passes tuple through, passes non-sequence through

---

## [x] Phase 0B: WS5 -- Gateway Resilience (parallel with WS3)

### Objective
Add circuit breaker pattern and model fallback chain to the LLM gateway.

### Files Created
- `src/nullvector/llm/circuit_breaker.py` -- `CircuitBreakerConfig`, `CircuitState`, `CircuitBreaker`

### Files Modified
- `src/nullvector/llm/types.py` -- add `fallback_models` and `circuit_breaker` fields to `GatewayConfig`
- `src/nullvector/llm/errors.py` -- add `GatewayCircuitOpenError`
- `src/nullvector/llm/service.py` -- modify `GatewayService.__init__` (hold per-model circuit breakers), modify `invoke()` retry loop
- `src/nullvector/llm/__init__.py` -- export new types

### Implementation

**Step 1** -- `circuit_breaker.py`:
```python
class CircuitBreakerConfig(NullVectorModel):
    failure_threshold: PositiveInt = 5
    recovery_timeout_seconds: PositiveFloat = 30.0
    half_open_max_calls: PositiveInt = 1

class CircuitBreaker:
    """Thread-safe circuit breaker. States: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    # Uses threading.Lock (sync-compatible, async migration wraps later)
    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...
    def allow_request(self) -> bool: ...
```

**Step 2** -- Extend `GatewayConfig`:
```python
fallback_models: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
```

**Step 3** -- Modify `GatewayService.invoke()`:
1. Before retry loop: check `circuit_breaker.allow_request()` for target model
2. If circuit open: try each `fallback_models` in order
3. If all circuits open: raise `GatewayCircuitOpenError`
4. On success: `record_success()`
5. On exhausted retries for TIMEOUT/NETWORK/UNKNOWN: `record_failure()`
6. RATE_LIMIT does NOT trip the circuit (transient)

**Backward compatibility**: `fallback_models` defaults to empty tuple, `CircuitBreakerConfig` defaults are permissive (threshold=5). Existing code unchanged.

### Validation
- New: `tests/unit/test_circuit_breaker_unit.py` -- state transitions, thread safety, recovery timeout
- Extend: `tests/unit/test_llm_gateway_unit.py` -- fallback model selection, circuit open behavior
- Existing gateway tests pass unchanged

---

## [x] Phase 1: WS1 -- Fix Storage Abstraction Leaks

### Objective
Remove all 18 backend-specific checks across 10 non-storage files. Services interact only through the `DocumentStore` protocol.

### Strategy
Replace identity checks with **capability queries** and **unified methods** on the protocol.

### Complete Leak Inventory (validated)

| File | Lines | Check Type |
|------|-------|-----------|
| `ingest/service.py` | 74 | `isinstance(..., PostgresStorageConfig)` |
| `ingest/acquisition_service.py` | 136 | `isinstance(..., PostgresStorageConfig)` |
| `retrieval/build.py` | 523, 590 | `isinstance` + `StorageBackend.POSTGRES` |
| `retrieval/service.py` | 157 | `StorageBackend.POSTGRES` |
| `retrieval/metadata_selection.py` | 244, 246, 280 | `StorageBackend.POSTGRES` |
| `retrieval/description.py` | 373 | `isinstance(..., PostgresStorageConfig)` |
| `retrieval/_tree_search_runtime.py` | 133, 138 | `isinstance` both configs |
| `retrieval/_selection_artifacts.py` | 20, 25 | `isinstance` both configs |
| `tree/service.py` | 302, 318, 621, 964 | `StorageBackend.POSTGRES` |
| `tree/compaction.py` | 636 | `isinstance(..., PostgresStorageConfig)` |

### Files Modified
- `src/nullvector/storage/protocol.py` -- add 3 new protocol members
- `src/nullvector/storage/filesystem.py` -- implement new members, no-op stubs
- `src/nullvector/storage/postgres.py` -- implement new members
- All 10 files in the leak inventory above

### Implementation

**Step 1** -- Add to `DocumentStore` protocol:
```python
def resolve_artifact_root(
    self, *, run_type: str, run_id: str, document_id: str,
    configured_root: str | None = None,
) -> str | None:
    """Canonical artifact root for one run. None when backend manages paths internally."""

@property
def supports_metadata_persistence(self) -> bool:
    """Whether backend can persist/query collection metadata."""

@property
def supports_retrieval_unit_queries(self) -> bool:
    """Whether backend supports store-backed retrieval unit queries."""
```

**Step 2** -- Filesystem implementation:
- `resolve_artifact_root()` -> returns constructed path from `configured_root` or `self._root`
- `supports_metadata_persistence` -> `False`
- `supports_retrieval_unit_queries` -> `False`
- `put_retrieval_units()` -> no-op returning the input count
- `complete_run()` -> writes the `run-index.json` status marker

**Step 3** -- Postgres implementation:
- `resolve_artifact_root()` -> returns `None`
- `supports_metadata_persistence` -> `True`
- `supports_retrieval_unit_queries` -> `True`

**Step 4** -- Refactor each service leak (all 10 files):
- `tree/service.py` -- `_tree_manifest_artifact_root()` -> `store.resolve_artifact_root()`; reserve_run/complete -> unified code path
- `tree/compaction.py` -- replace isinstance with `store.resolve_artifact_root()`
- `retrieval/build.py` -- call `put_retrieval_units()` unconditionally; replace isinstance for store construction
- `retrieval/service.py` -- check `supports_retrieval_unit_queries` instead of `backend`
- `retrieval/metadata_selection.py` -- check `supports_metadata_persistence` instead of `backend`
- `retrieval/description.py` -- replace isinstance with protocol-based store resolution
- `retrieval/_tree_search_runtime.py` -- replace isinstance checks with `store.resolve_artifact_root()`
- `retrieval/_selection_artifacts.py` -- replace isinstance checks with `store.resolve_artifact_root()`
- `ingest/service.py` -- replace isinstance with `store.resolve_artifact_root()`
- `ingest/acquisition_service.py` -- replace isinstance with `store.resolve_artifact_root()`

### Validation
- `grep -rn "StorageBackend\." src/nullvector/` must match ONLY files under `src/nullvector/storage/`
- `grep -rn "isinstance.*StorageConfig" src/nullvector/` must match ONLY `src/nullvector/storage/factory.py`
- Full test suite: `uv run pytest tests/`
- Add protocol contract tests ensuring both backends satisfy capability queries

---

## [x] Phase 2: WS4 -- Extract Side-Effects from God Functions

### Objective
Decompose `TreePipelineService.build()` (~400 lines) and `RetrievalCorpusBuilder.build()` (~200 lines) into named phase methods accepting a `RunContext`.

### Files Created
- `src/nullvector/runtime/__init__.py`
- `src/nullvector/runtime/context.py` -- `RunContext` dataclass

### Files Modified
- `src/nullvector/tree/service.py` -- decompose `build()` into ~6 named private methods
- `src/nullvector/retrieval/build.py` -- decompose `build()`

### Implementation

**Step 1** -- `RunContext`:
```python
@dataclass(frozen=True)
class RunContext:
    store: DocumentStore
    run_store: RunScopedStore
    artifact_root: str | None
    logger: Logger
```

**Step 2** -- Decompose `TreePipelineService.build()` into:
- `_resolve_input_bundle(request) -> InputBundle`
- `_reserve_or_reuse(ctx, request, ...) -> TreeBuildManifest | None`
- `_run_hierarchy_pipeline(ctx, ...) -> HierarchyResult`
- `_run_verification(ctx, ...) -> VerificationResult`
- `_run_summarization(ctx, ...) -> SummarizationResult`
- `_persist_and_finalize(ctx, ...) -> TreeBuildManifest`

The `build()` method becomes a ~50-line orchestrator calling these in sequence.

**Step 3** -- Apply same decomposition pattern to `RetrievalCorpusBuilder.build()`.

### Validation
- All existing integration tests pass unchanged
- Each extracted method individually testable with mock `RunContext`
- New unit tests for phase methods
- `make ci` green

---

## [x] Phase 3: WS2 -- Migrate from Threads to asyncio

### Objective
Add async variants alongside existing sync methods. Dual-interface approach -- no breaking changes.

### Files Created
- `src/nullvector/llm/async_service.py` -- `AsyncGatewayService`
- `src/nullvector/storage/async_postgres.py` -- `AsyncPostgresDocumentStore`

### Files Modified
- `src/nullvector/llm/protocols.py` -- add `AsyncStructuredLLMGateway`, `AsyncProviderAdapter` protocols
- `src/nullvector/llm/adapters/_openai.py` -- add `AsyncOpenAIAdapter`
- `src/nullvector/llm/adapters/_litellm.py` -- add `AsyncLiteLLMAdapter`
- `src/nullvector/ingest/acquisition_service.py` -- add `async_acquire_batch()`
- `src/nullvector/tree/service.py` -- add `async_build_tree_batch()`
- `src/nullvector/storage/protocol.py` -- add `AsyncDocumentStore` protocol
- `pyproject.toml` -- add `pytest-asyncio` to dev deps

### Key Design Decisions
- `asyncio.Semaphore` replaces `ThreadPoolExecutor` for concurrency control
- CPU-bound PDF parsing uses `asyncio.to_thread()` to avoid blocking the event loop
- `psycopg.AsyncConnection` (already available in `psycopg>=3.1.0`) for async Postgres
- OpenAI SDK's `AsyncOpenAI` and LiteLLM's `acompletion` for async LLM calls
- Sync API fully preserved -- no breaking changes

### Dependency Review Required
- `pytest-asyncio` -- dev-only dependency, must complete dependency intelligence gate before adding

### Validation
- All existing sync tests pass unchanged
- New async test suite using `pytest-asyncio`
- Integration test: async acquire + async tree build on test PDF
- `make ci` green

---

## [x] Phase 4: WS6 -- Developer Experience

### Objective
Create `NullVectorClient` facade, archetype presets, CLI, and semantic error translation.

### Files Created
- `src/nullvector/client.py` -- `NullVectorClient` facade
- `src/nullvector/presets.py` -- archetype presets (academic_paper, financial_report, legal_contract, etc.)
- `src/nullvector/cli.py` -- Typer CLI (`nv ingest`, `nv build-tree`, `nv search`, `nv ask`)
- `src/nullvector/errors.py` -- public exception hierarchy (`NullVectorError`, `IngestionError`, etc.)

### Files Modified
- `pyproject.toml` -- add `typer` dependency, `[project.scripts]` entry
- `src/nullvector/__init__.py` -- export facade, presets, errors

### Dependency Review Required
- `typer` -- production dependency, must complete dependency intelligence gate before adding
- Evaluate whether `typer` is justified vs `click` or stdlib `argparse`

### Key Design
```python
# Three-line usage:
client = NullVectorClient(storage_path="./workspace")
manifest = client.ingest("quarterly_earnings.pdf", preset="financial_report")
response = client.ask("What was Q3 revenue?", document_id=manifest.document_id)
```

Error translation catches `pydantic.ValidationError`, `ParseSubstrateError`, `GatewayError`, `GatewayCircuitOpenError` and re-raises as actionable `NullVectorError` subtypes.

`scripts/nullvector_quickstart.py` is refactored into a thin wrapper over the facade so existing quickstart tests keep passing.

### Validation
- Unit tests for facade with mocked storage/gateway
- Unit tests for preset resolution
- CLI smoke test: `nullvector ingest <pdf> --preset academic_paper`
- Error translation coverage: each internal exception -> correct public exception
- `make ci` green

---

## Verification Plan (End-to-End)

After all phases:
1. `uv run pytest tests/` -- full suite, zero failures
2. `uv run mypy --strict src/nullvector/` -- zero errors
3. `uv run ruff check src/nullvector/` -- zero warnings
4. `grep -rn "StorageBackend\." src/nullvector/` -- only in `storage/` directory
5. `grep -rn "isinstance.*StorageConfig" src/nullvector/` -- only in `storage/factory.py`
6. Zero deprecation warnings (enforced by pytest `filterwarnings = ["error::DeprecationWarning"]`)
7. Integration test: ingest PDF -> build tree -> search -> ask, both filesystem and Postgres backends
8. Async integration test: same pipeline using async facade methods
9. `notebooks/progress.ipynb` executes top-to-bottom cleanly
10. Each phase appends filtered diff to `CHANGE_DIFF.md` (respecting `.diffignore`)

## Rollback
Each phase is independently deployable. If a phase causes regressions:
- Revert the phase's commits
- Prior phases remain intact
- No phase modifies public API contracts (WS6 is purely additive)
