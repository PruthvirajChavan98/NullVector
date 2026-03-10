# Engineering Rules

## Code quality
- Use strict typing everywhere.
- Prefer explicit interfaces over ad hoc dicts.
- No deprecated APIs.
- No warning suppression unless explicitly justified in comments and ADRs.
- No regex-based JSON cleanup for model outputs.
- No hidden global state.
- No business logic in request handlers.
- No swallowing exceptions.

## Async rules
- Request handlers must remain non-blocking.
- CPU-heavy work must go to worker processes or workflow activities.
- DB access must be async-only.
- Never share mutable DB session objects across concurrent tasks.
- Use bounded concurrency with explicit semaphores or queue limits.

## Parsing rules
- Native outline extraction is always attempted first.
- Native text extraction is always attempted before OCR.
- OCR is fallback, not default.
- Every page gets a ledger entry.
- Every tree node must resolve to a concrete page span.
- Every summary must keep source anchors.

## LLM rules
- LLM calls are adapter-mediated only.
- Every model output must use schema-constrained structured output where supported.
- Every model response is validated into typed models before downstream use.
- On validation failure, return a typed error envelope and preserve the raw payload for audit.
- Prompts must ask for grounded extraction, not free-form interpretation.
- Retries must be bounded and logged.

## Storage rules
- Persist immutable parse artifacts per run.
- Version hierarchy outputs.
- Keep raw extraction, repaired extraction, and committed hierarchy distinct.
- Make all verification reports diffable and queryable.

## Testing rules
- Every parser bug gets a fixture or regression test.
- Add corpus tests for multi-hundred-page and scanned PDFs.
- Add idempotency tests for workflow retries.
- Add schema round-trip tests for all LLM-bound models.
- Add concurrency tests for job orchestration.

## Documentation rules
- Update ADRs for architectural decisions.
- Update phase prompt status when a phase is completed.
- Update runbooks when operational behavior changes.

