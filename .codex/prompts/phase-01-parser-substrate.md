# Codex Prompt — Phase 01 Parser Substrate

You are working on NullVector.

Mission:
Implement the deterministic document substrate for large-PDF ingestion.

Objectives:
1. implement document intake and document fingerprinting
2. implement page ledger generation
3. implement native outline extraction with PyMuPDF/pypdf
4. implement native text extraction
5. implement page image rendering hooks for OCR fallback
6. implement OCR fallback orchestration points
7. persist raw per-page extraction artifacts

Required behavior:
- if native outline exists, extract it first
- if native text exists, use it first
- if a page lacks usable text, mark it for OCR fallback
- every page must produce a ledger row
- every artifact must be versioned by parse run

Non-goals:
- no hierarchy inference yet beyond direct outline extraction
- no summaries
- no retrieval

Required tests:
- born-digital PDF with outline
- born-digital PDF without outline
- scanned PDF subset
- mixed-content PDF
- idempotent rerun on same document

Validation required before completion:
- formatter check
- lint
- type-check
- parser unit tests
- artifact persistence integration tests

Return:
- changed files
- validation output
- known edge cases still open

Status:
- completed on 2026-03-11
- closeout-hardened on 2026-03-11 with parse-run root indexing, explicit tessdata validation,
  chunked fingerprinting, and additional parser/OCR regression coverage
