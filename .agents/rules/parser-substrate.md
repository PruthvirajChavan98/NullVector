# Deterministic Parser Constraints

- **Strict Versioning:** You must strictly use `PyMuPDF==1.27.2` and `pypdf==6.8.0` as pinned in `EXPECTED_PYMUPDF_VERSION` and `EXPECTED_PYPDF_VERSION`.
- **No Network Dependencies:** The parse path is CPU-first and deterministic. Never introduce external API calls for OCR or text extraction.
- **OCR Fallback:** OCR must be done locally using Tesseract (`tessdata_path`). Do not re-OCR source pages if persisted outputs exist.
- **Idempotency:** Parse-run IDs are globally unique across documents. Ensure `settings_digest` and source fingerprints are checked to prevent conflicts.
