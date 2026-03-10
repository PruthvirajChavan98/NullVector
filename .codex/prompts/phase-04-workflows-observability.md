# Codex Prompt — Phase 04 Workflows and Observability

You are working on StrataForge.

Mission:
Implement durable workflow orchestration and production observability for large document ingestion.

Objectives:
1. implement the ingestion state graph:
   ingest -> extract_outline -> extract_text -> ocr_fallback? -> build_tree -> summarize -> verify -> commit
2. ensure every step is idempotent
3. add resumability and replay-safe state transitions
4. move CPU-bound work off the API event loop
5. add bounded concurrency controls for page batches
6. add poison-batch handling and dead-letter strategy
7. instrument workflow steps with OpenTelemetry traces, metrics, and structured logs
8. add SSE progress events from job state transitions

Rules:
- API handlers remain non-blocking
- no shared mutable async DB session across concurrent tasks
- state transitions must be explicit and persisted
- failures must retain exact tracebacks
- every retry attempt must be logged with causal context

Required metrics:
- job duration
- stage duration
- OCR fallback rate
- verification failure rate
- retry count
- batch throughput
- queue lag
- commit success/failure rate

Required tests:
- workflow happy path
- retry path
- worker restart/recovery path
- partial-batch failure path
- SSE progress contract test

Validation required before completion:
- formatter check
- lint
- type-check
- workflow integration tests
- observability smoke tests

Return:
- changed files
- validation output
- remaining scale risks

