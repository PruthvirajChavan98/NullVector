# ADR 0002: Deterministic Parser Substrate with Dual Outline Scoring and Local OCR

- Status: accepted
- Date: 2026-03-11

## Context

Phase 01 needs a deterministic parser substrate for large PDFs with parse-run artifact persistence,
native outline extraction, native text extraction, and local OCR fallback. The repository requires a
CPU-first parse path with no hidden network dependency and reproducible golden fixtures.

## Decision

Implement the parser substrate with:

- exact parser pins: `PyMuPDF==1.27.2` and `pypdf==6.8.0`
- PyMuPDF as the primary text extractor and one outline source
- `pypdf` as the second outline source, normalized and scored against PyMuPDF output
- scored outline selection based on entry count, null destinations, title quality, monotonicity,
  and depth validity
- explicit local Tesseract configuration through `tessdata_path`
- multi-signal OCR gating with partial-vs-full OCR mode selection
- a parse-run root index at `artifacts/parse_runs/{parse_run_id}/run-index.json` so `parse_run_id`
  is globally unique across documents
- parse-run artifacts stored under `artifacts/parse_runs/{parse_run_id}/{document_id}`
- idempotency keyed by source fingerprint plus effective parser settings digest
- chunked source hashing plus file-path-based page counting for lower memory pressure on large PDFs
- selective gzipped rawdict persistence instead of full rawdict snapshots for every page
- image coverage treated as an approximate OCR heuristic because overlapping or transformed images
  can overcount before clamping
- PyMuPDF usage gated for production release on commercial-license review/approval

## Consequences

- Fixture stability is improved because parser behavior is locked to exact versions during the
  golden-fixture phase.
- Outline selection is based on normalized quality metrics instead of hardcoded parser preference.
- OCR remains local and explicit, but environments running OCR tests must install Tesseract and
  tessdata.
- Reusing a `parse_run_id` across different documents or settings is now a deterministic conflict.
- Large-PDF fingerprinting avoids loading the entire file into memory just to compute a hash.
- Later phases must consume persisted OCR outputs instead of re-OCRing source pages.
- Technical completion of Phase 01 does not imply production release approval until PyMuPDF
  commercial-license review is complete.
