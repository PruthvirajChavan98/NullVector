# ADR 0007: V2 Acquisition Runtime and Additive Tree Cutover

- Status: accepted
- Date: 2026-03-12

## Context

ADR 0006 introduced the additive v2 ledger and projection contracts, but the repository runtime was
still centered on:

- `ParseRunManifest`
- `PageLedgerRow`
- `artifacts/parse_runs/`
- tree input reconstruction from persisted parse text/rawdict artifacts

`major-changes-v2.md` requires the next migration step:

- a framework-owned v2 acquisition lifecycle
- a separate artifact namespace for acquisition runs
- a native-first provider that emits `CanonicalDocumentLedger`
- a persisted `TreeSynthesisView`
- additive tree cutover so the existing tree pipeline can consume either legacy parse manifests or
  new acquisition manifests

## Decision

Introduce a parallel v2 runtime with these boundaries:

- acquisition lifecycle:
  - `AcquisitionRequest`
  - `AcquisitionRunIndex`
  - `AcquisitionRunManifest`
- separate artifact namespace:
  - `artifacts/acquisition_runs/{acquisition_run_id}/{document_id}/`
- framework-owned native provider:
  - `NativePyMuPDFAcquisitionProvider`
- separate projection step:
  - `project_ledger_to_tree_synthesis_view(...)`
- additive tree input contract:
  - `TreeBuildRequest.parse_manifest_path`
  - `TreeBuildRequest.acquisition_manifest_path`
  - exactly one must be provided

The v2 runtime persists:

- source copy and fingerprint
- canonical document ledger
- outline artifacts
- document/page event stream
- tree synthesis view
- acquisition manifest and run index

The tree pipeline continues to use the existing internal heading, TOC, verification, hierarchy,
strategy, decomposition, and summarization logic. Only the input boundary is changed:

- legacy path reconstructs `PageArtifacts` from parse artifacts
- v2 path reconstructs `PageArtifacts` from `TreeSynthesisView`

## Consequences

- The migration is additive and preserves the legacy parse/tree runtime as the acceptance baseline.
- New born-digital documents can now be acquired and projected without invoking the legacy OCR
  substrate.
- The tree pipeline can exercise projection-backed parity without directly reading provider-native
  payloads.
- Projection fidelity is now the critical migration seam: if normalized line-layout signals are too
  lossy, tree parity will drift even when the high-level architecture is correct.
- Legacy cleanup, tokenizer boundaries, observability/event-bus wiring, and export adapters remain
  explicitly deferred until projection-backed parity is established more broadly.
