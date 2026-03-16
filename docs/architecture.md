# Architecture Reference

> On-demand reference for Claude Code. Load with `@docs/architecture.md` when working on
> cross-cutting concerns, adding new modules, or evaluating architectural fit of a change.

---

## What NullVector Is

NullVector is a **CPU-first document hierarchy framework for deterministic PDF ingestion**.
It is a Python library -- not a web application. It has no HTTP endpoints, no CLI entry
point, no ASGI server, and no async runtime. It is imported and used programmatically.

All processing is **synchronous** unless an external LLM provider introduces latency.
Determinism is enforced through exact version pins on PDF parsers and content-addressed
fingerprinting.

---

## High-Level Architecture

NullVector follows a **protocol-based layered architecture**. Each processing phase is a
self-contained package under `src/nullvector/`. Phases communicate through typed Pydantic
domain models and persist artifacts through the `DocumentStore` protocol.

```
                    +-----------+
                    |  domain/  |   Authoritative Pydantic contracts
                    +-----+-----+
                          |
     +--------+-----------+-----------+---------+--------+
     |        |           |           |         |        |
  ingest/   tree/       llm/     retrieval/ semantic/ export/
  Phase 01  Phase 02   Phase 03   Phase 04   Phase 05  Bridges
     |        |           |           |         |
     +--------+-----------+-----------+---------+
                          |
                    +-----+-----+
                    |  storage/ |   DocumentStore protocol boundary
                    +-----------+
```

Dependencies flow inward toward `domain/` and downward toward `storage/`. Processing
phases depend on domain contracts but never on each other's internals.

---

## Processing Phases

### Phase 01: Ingest (`ingest/`)

Acquires a PDF, extracts text and images, and builds the canonical ledger.

| Module | Responsibility |
|--------|---------------|
| `acquisition_service.py` | V2 acquisition runtime (uses DocumentStore) |
| `service.py` | Legacy parse service |
| `providers/native_pymupdf.py` | PyMuPDF-based extraction provider |
| `protocols.py` | `AcquisitionProvider`, `TranslationAdapter` contracts |
| `fingerprint.py` | Content-addressed document fingerprinting |
| `projection.py` | Page-level projection and span assembly |
| `text.py` | Text extraction and normalization |
| `ocr.py` | OCR integration for image-heavy pages |
| `outline.py` | PDF outline / bookmark extraction |
| `profiling.py` | Page profiling and classification |
| `visual_assets.py` | Image and figure extraction |
| `artifacts.py`, `acquisition_artifacts.py` | Typed artifact containers |
| `errors.py` | `ParseSubstrateError` hierarchy |

### Phase 02: Tree (`tree/`)

Builds a deterministic document hierarchy from headings, outlines, and TOC data.

| Module | Responsibility |
|--------|---------------|
| `service.py` | `TreePipelineService` orchestrator |
| `strategy.py` | Hierarchy strategy selection |
| `headings.py` | Heading extraction and font-size scoring |
| `hierarchy.py` | Hierarchy synthesis from scored headings |
| `repair.py` | `RepairEngine` protocol + `NoopRepairEngine` |
| `verify.py` | Tree verification against source text |
| `toc.py` | TOC extraction from PDF outline |
| `toc_reconcile.py` | TOC-to-heading reconciliation |
| `anchors.py` | Line anchoring for heading positions |
| `_constants.py` | Tree-specific constants |

### Phase 03: LLM (`llm/`)

Optional enrichment via a typed LLM gateway. Supports repair, summarization,
verification, and TOC generation through structured prompts.

| Module | Responsibility |
|--------|---------------|
| `service.py` | `GatewayService` (sync-first, retries, auditing) |
| `protocols.py` | `ProviderAdapter`, `StructuredLLMGateway` contracts |
| `types.py` | `GatewayRequest`, `GatewaySuccess`, `GatewayFailure` |
| `errors.py` | `GatewayError` hierarchy (validation, timeout, rate limit, etc.) |
| `audit.py` | LLM call audit trail |
| `retry.py` | Retry logic for transient failures |
| `providers/litellm_sdk.py` | LiteLLM SDK adapter |
| `providers/openai_http.py` | Direct OpenAI HTTP adapter |
| `providers/noop.py` | No-op adapter for testing |
| `prompts/` | Prompt templates: `repair.py`, `summarization.py`, `verification.py`, `toc.py`, `toc_reconcile.py`, `decomposition.py` |

The gateway uses **typed failure envelopes** (`GatewaySuccess | GatewayFailure`) for
expected failures instead of exceptions. Unexpected failures raise typed exceptions from
the `GatewayError` hierarchy.

### Phase 04: Retrieval (`retrieval/`)

Builds a searchable corpus from the document hierarchy and supports query planning,
ranking, and QA response generation.

| Module | Responsibility |
|--------|---------------|
| `service.py` | `RetrievalService` orchestrator |
| `build.py` | `RetrievalCorpusBuilder` |
| `planner.py` | `QueryPlanner` for multi-step retrieval |
| `rank.py` | `RetrievalRanker` for result scoring |
| `index.py` | In-memory and PostgreSQL index backends |
| `qa.py` | QA response generation |
| `load.py` | Corpus loading utilities |
| `enrichment.py` | Retrieval unit enrichment |

### Phase 05: Semantic (`semantic/`)

Decomposes tree nodes and generates summaries.

| Module | Responsibility |
|--------|---------------|
| `decompose.py` | `NodeDecomposer` |
| `summarize.py` | `NodeSummarizer` |
| `tokens.py` | Tokenizer protocol and heuristic token counting |

### Export (`export/`)

Edge-only bridges for external frameworks. These are thin adapters that convert
NullVector's internal types into formats consumed by LangChain or LlamaIndex.

| Module | Responsibility |
|--------|---------------|
| `langchain.py` | LangChain `Document` bridge |
| `llamaindex.py` | LlamaIndex `TextNode` bridge |

---

## Domain Layer (`domain/`)

All domain types inherit from `StrataModel` (defined in `domain/common.py`), which
enforces `frozen=True`, `extra="forbid"`, `strict=True`.

| Module | Contents |
|--------|----------|
| `common.py` | `StrataModel` base, `BoundingBox`, `NonEmptyStr`, `Sha256Hex`, `ScalarValue` |
| `ledger.py` | Parse manifests, `DocumentFingerprint`, canonical ledger types |
| `tree.py` | `HierarchyNode`, tree synthesis types, repair types |
| `events.py` | `DocumentEvent`, `PageEvent`, provenance tracking |
| `gateway.py` | LLM gateway response types |
| `retrieval.py` | Retrieval corpus, hits, evidence types |

---

## Storage Layer (`storage/`)

All persistence goes through the `DocumentStore` protocol. Services receive a
`RunScopedStore` handle scoped to a single processing run.

| Module | Responsibility |
|--------|---------------|
| `protocol.py` | `DocumentStore` and `RunScopedStore` protocol definitions |
| `filesystem.py` | `FilesystemDocumentStore` -- default backend, no dependencies |
| `postgres.py` | `PostgresDocumentStore` -- optional, requires `psycopg` |
| `factory.py` | `build_document_store()` factory |
| `config.py` | `StorageConfig`, `StorageBackend` types |
| `_serialization.py` | Internal serialization helpers |

The `DocumentStore` protocol provides:
- Document registration via content-addressed fingerprints
- Atomic run reservation and completion
- JSON, JSONL, text, and binary artifact persistence
- Retrieval unit bulk storage and querying
- Audit and event append-only logs

---

## Observability (`observability/`)

| Module | Responsibility |
|--------|---------------|
| `logging.py` | `log_event()` and typed event helpers |
| `subscribers/json_logger.py` | JSONL structured log subscriber |
| `subscribers/rich_progress.py` | Rich terminal progress bar subscriber |

---

## Key Design Patterns

### Protocol-based boundaries

All inter-layer contracts are defined as `typing.Protocol` classes:
- `AcquisitionProvider` (ingest)
- `ProviderAdapter` / `StructuredLLMGateway` (llm)
- `DocumentStore` / `RunScopedStore` (storage)
- `RepairEngine` (tree)

### Typed failure envelopes

The LLM gateway returns `GatewaySuccess | GatewayFailure` union types rather than
raising exceptions for expected failure modes (rate limits, validation errors, timeouts).

### Deterministic outputs

- PyMuPDF pinned to exact version (`==1.27.2`) for bit-identical extraction
- pypdf pinned to exact version (`==6.8.0`) for outline extraction
- Content-addressed fingerprinting via SHA-256

### Artifact-driven pipelines

Each processing phase produces typed artifacts persisted through the `DocumentStore`.
Artifacts are referenced by deterministic paths derived from run type, run ID, and
document ID.

---

## ADRs (Authoritative)

The `docs/adr/` directory contains the actual architectural decision records:

| ADR | Topic |
|-----|-------|
| 0001-0003 | Bootstrap, parser substrate, tree pipeline |
| 0004 | LLM gateway design |
| 0005 | Tree enhancements (TOC, strategy, decomposition) |
| 0006 | V2 ledger and projection contracts |
| 0007 | Acquisition runtime |
| 0008 | Major v2 changes |

Reference individual ADRs as `@docs/adr/0004-llm-gateway-design.md`.
