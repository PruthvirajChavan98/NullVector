# StrataForge

StrataForge is a CPU-first document hierarchy framework for deterministic ingestion of large
technical PDFs into verifiable hierarchical JSON artifacts.

## Current Scope

This repository currently establishes:

- authoritative typed domain contracts with Pydantic v2
- strict local validation tooling
- deterministic Phase 01 parser substrate for document intake, outline extraction, text extraction,
  OCR gating, and parse-run artifact persistence
- deterministic Phase 02 tree pipeline for heading extraction, hierarchy assembly, explicit
  unassigned-page tracking, verification, and typed repair artifacts
- Phase 03 typed LLM gateway with StrataForge-owned retries, audit capture, transport-compatible
  LiteLLM support, a provider-native strict OpenAI Responses adapter, and bounded repair
  integration
- test fixtures, golden expectations, and ADR scaffolding for later phases

## Local Development

```bash
uv sync --extra dev
make ci
```

Full OCR-backed validation requires local Tesseract language data. On Debian-based systems:

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng
```

Production release remains gated on PyMuPDF commercial-license review. See
`docs/legal/pymupdf-licensing.md`.

## Phase 03 LLM Gateway

The canonical gateway surface lives under `src/strataforge/llm/` and is intentionally split across
three subphases:

- `03A`: typed gateway core, noop adapter, and LiteLLM SDK adapter with
  `transport_compatible` assurance only
- `03B`: direct OpenAI Responses adapter with `provider_native_strict` assurance plus bounded tree
  repair integration
- `03C`: failure hardening, audit stabilization, docs, and notebooks

Current runtime requirements for live provider use:

- LiteLLM SDK examples may use provider-specific environment variables such as `OPENAI_API_KEY`
- the direct OpenAI Responses adapter requires `OPENAI_API_KEY`
- notebook live cells are opt-in and env-gated; mocked/noop examples remain the default path

The gateway core owns:

- request and response contracts
- Pydantic validation
- typed failure normalization
- retry and backoff policy
- redacted audit persistence

Provider adapters are transport boundaries only. The LiteLLM proxy/server path is out of scope for
Phase 03.

## Tree Pipeline Major Changes

The tree pipeline now includes the major additive extensions implemented after the original Phase 02
baseline:

- deterministic-first TOC detection over persisted parse artifacts, with optional typed LLM
  fallback for ambiguous pages
- TOC-to-heading reconciliation with bounded page-offset calculation and TOC-derived candidates
- opt-in grounded LLM verification assistance only when deterministic title matching fails
- bottom-up node summarization, still off by default unless a gateway is supplied
- bounded strategy orchestration across outline, TOC-derived, and inferred paths
- deterministic-first large-leaf decomposition before final summarization, with optional bounded LLM
  fallback when deterministic subdivision fails

Existing default behavior is preserved when no gateway is provided and no optional summarize path is
requested.

## Validation Commands

```bash
make format-check
make lint
make typecheck
make test
```

## Notebook Execution

The canonical runnable notebook is:

- `notebooks/progress.ipynb`
- `notebooks/phase03_llm_gateway_cookbook.ipynb`
- `notebooks/spec_v1_parser_tree_demo.ipynb` for local real-document parser/tree inspection

The Phase 03 cookbook includes deterministic mocked sections plus an optional Moonshot LiteLLM
transport probe. That Moonshot probe is skipped by default, is not Phase 03 acceptance evidence,
and should not be treated as validated structured-output support for the current LiteLLM
responses-style path.

To execute it deterministically and persist an executed copy under `notebooks/_artifacts/`:

```bash
uv run python scripts/run_progress_notebook.py
```

To execute the cookbook notebook:

```bash
uv run python scripts/run_progress_notebook.py \
  --notebook notebooks/phase03_llm_gateway_cookbook.ipynb \
  --output notebooks/_artifacts/phase03-cookbook.executed.ipynb
```

To execute the local real-PDF parser/tree demo notebook:

```bash
uv run python scripts/run_progress_notebook.py \
  --notebook notebooks/spec_v1_parser_tree_demo.ipynb \
  --output notebooks/_artifacts/spec_v1_parser_tree_demo.executed.ipynb
```

This local operator demo depends on `903000608.pdf` being present at the repository root and may
reuse or create notebook-local artifacts under `notebooks/artifacts/parse_runs/`. It is not a
committed fixture or CI acceptance path.

## Progress Notebook

A canonical manual verification notebook is maintained at:

- `notebooks/progress.ipynb`
- `notebooks/phase03_llm_gateway_cookbook.ipynb`
- `notebooks/spec_v1_parser_tree_demo.ipynb` for the local real-document parser/tree walkthrough

It is intended to let you exercise the current phase implementation without reconstructing commands from chat history.
