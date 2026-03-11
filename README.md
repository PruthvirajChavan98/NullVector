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

To execute it deterministically and persist an executed copy under `notebooks/_artifacts/`:

```bash
uv run python scripts/run_progress_notebook.py
```

## Progress Notebook

A canonical manual verification notebook is maintained at:

- `notebooks/progress.ipynb`

It is intended to let you exercise the current phase implementation without reconstructing commands from chat history.
