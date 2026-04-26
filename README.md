# NullVector

> Vectorless hierarchical RAG framework — VLM transcription + LLM-driven section trees, no embeddings.

NullVector processes PDFs and Markdown into auditable, searchable hierarchical trees without
vector embeddings. PDF pages are rendered to images and transcribed to Markdown via a VLM, then
an LLM synthesizes the document hierarchy. All retrieval is structural (tree traversal,
LLM-driven ranking) with full traceability back to source pages.

## Why vectorless?

- **Provenance** — every hit traces back to a specific page and section anchor, not a cosine distance.
- **No embedding infrastructure** — no vector DB, no index to rebuild when the corpus changes.
- **Explainable retrieval** — the LLM ranks candidates based on structural context, not opaque vector math.

## Quickstart

```python
from pathlib import Path
from nullvector import NullVectorClient
from nullvector.llm import GatewayConfig, GatewayService
from nullvector.llm.adapters import LiteLLMAdapter

# 1. Build a gateway (LiteLLM → any provider; OpenRouter, Groq, OpenAI, etc.)
gateway = GatewayService(
    GatewayConfig(default_model="openrouter/google/gemini-2.5-flash-lite-preview-09-2025"),
    provider_adapter=LiteLLMAdapter(api_key="..."),  # or from env
)

# 2. Create the client
client = NullVectorClient(Path("./workspace"), gateway=gateway)

# 3. Ingest a PDF (VLM transcription + tree build + retrieval index)
result = client.ingest("document.pdf")

# 4. Ask questions with grounded citations
answer = client.ask("What does the methodology section cover?", ingest_result=result)
print(answer.answer)
for citation in answer.citations:
    print(f"  page {citation.page_label}: {citation.quote}")
```

## Core Features

- **Parallel VLM transcription** — pages transcribed concurrently via `invoke_many`. Configurable
  via `AcquisitionSettings.vlm_max_concurrent_pages` (default: 4).
- **Semantic anchoring** — the VLM emits `<!-- SECTION_ANCHOR: level=N, title='...' -->` markers
  before each heading, giving tree nodes spatial provenance back to the source page.
- **Map-reduce hierarchy synthesis** — documents with 15+ pages are split into overlapping
  chunks, analyzed in parallel, then merged. Avoids the "lost in the middle" problem for
  long documents.
- **Raw-text gateway path** — `GatewayService.invoke_text()` for non-structured calls,
  eliminating JSON escaping failures for content with quotes, backslashes, or newlines.
- **Dual storage backends** — `FilesystemDocumentStore` (zero-dependency default) and
  `PostgresDocumentStore` (optional, `uv sync --extra postgres`).
- **Structured retrieval** — tree search + LLM-driven ranking + grounded QA with page citations.
- **Typed LLM gateway** — provider-agnostic, with NullVector-owned retries, audit capture,
  circuit breakers, and typed failure envelopes.

## Architecture

```
PDF / Markdown
    │
    ▼
┌─────────────────┐   VLM page transcription (parallel) + section anchor extraction
│   Acquisition   │   → CanonicalDocumentLedger (VLM Markdown + SectionAnchorRecord)
└────────┬────────┘
         ▼
┌─────────────────┐   LLM hierarchy synthesis (single-shot or map-reduce)
│   Tree Build    │   → HierarchyNode tree (sections with source anchors)
└────────┬────────┘
         ▼
┌─────────────────┐   Retrieval corpus from tree nodes
│ Retrieval Index │   → RetrievalCorpus (searchable units with page refs)
└────────┬────────┘
         ▼
┌─────────────────┐   LLM-driven tree search + ranking + grounded QA
│  Search / QA    │   → RetrievalHit[] + Answer with page citations
└─────────────────┘
```

## Installation

```bash
# Core library + dev tools
uv sync --extra dev

# Optional Postgres backend
uv sync --extra dev --extra postgres
```

On Debian-based systems, OCR-backed Markdown fixtures need tesseract:

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng
```

## Configuration

NullVector reads configuration from environment variables. See `.env.example` for the
complete list. Copy it and fill in your keys:

```bash
cp .env.example .env
# edit .env with your OPENROUTER_API_KEY or GROQ_API_KEYS
```

Core variables:

| Variable | Purpose |
|----------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key (cookbook quickstart default) |
| `GROQ_API_KEYS` | Comma-separated Groq keys (cookbook LangGraph agent) |
| `NULLVECTOR_LLM_MODEL` | LiteLLM model identifier |
| `NULLVECTOR_POSTGRES_CONNINFO` | Postgres DSN (if using Postgres backend) |
| `NULLVECTOR_OBSERVABILITY_JSONL_PATH` | Structured event log location |

## Cookbook

Two end-to-end notebooks in `cookbook/`:

- **`cookbook/01_nullvector_quickstart.ipynb`** — PDF → hierarchy → search → grounded QA
  using `NullVectorClient` with Postgres storage and OpenRouter/Gemini.
- **`cookbook/02_langgraph_agent.ipynb`** — LangGraph ReAct agent backed by NullVector
  grounded QA. Depends on cookbook 01's corpus.

Both rely on environment variables from `.env` — no hardcoded secrets.

## CLI

A thin CLI is installed as `nullvector` and `nv`:

```bash
uv run nullvector ingest document.pdf
uv run nv search "your query" --document-id <id>
uv run nv ask "What does section 3 cover?" --document-id <id>
```

For a scriptable quickstart without the CLI:

```bash
uv run python scripts/nullvector_quickstart.py \
  --source-path fixtures/pdfs/phase01/born_digital_with_outline.pdf
```

## Validation

```bash
make format   # ruff format
make lint     # ruff check
make typecheck  # mypy strict
make test     # pytest
make ci       # all of the above
```

Pytest enforces `filterwarnings = ["error::DeprecationWarning"]` — deprecation warnings are
test failures.

## Repository Layout

- `src/nullvector/` — framework packages and public DX entrypoints
- `src/nullvector/client.py` — `NullVectorClient` high-level facade
- `src/nullvector/ingest/` — VLM page transcription and acquisition
- `src/nullvector/tree/` — LLM hierarchy synthesis (single-shot + map-reduce)
- `src/nullvector/retrieval/` — corpus, search, ranking, QA
- `src/nullvector/llm/` — typed gateway, provider adapters, prompt builders
- `src/nullvector/storage/` — filesystem and Postgres backends
- `tests/` — unit, integration, retrieval test suites
- `cookbook/` — runnable end-to-end notebooks
- `docs/` — architecture notes and ADRs
- `scripts/` — operator and development scripts

## Licensing

NullVector pins `PyMuPDF==1.27.2` for page rendering. Production use requires a review of
PyMuPDF's AGPL / commercial licensing. See `docs/legal/pymupdf-licensing.md`.
