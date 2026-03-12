# ADR 0006: Additive V2 Ledger and Projection Contracts

- Status: accepted
- Date: 2026-03-12

## Context

`major-changes-v2.md` changes the architectural direction of StrataForge in two important ways
before any acquisition or tree logic is rewritten:

- acquisition should converge on a canonical document ledger instead of treating
  `PageLedgerRow` as the long-term boundary
- tree synthesis should eventually consume a normalized projection layer instead of provider-facing
  acquisition artifacts

The repository also needs to stop treating `domain/models.py` as a permanent monolith. The current
codebase is already large enough that parse, tree, gateway-prompt, provenance, and future v2
acquisition schemas should not all share one implementation file.

## Decision

Introduce an additive v2 contract layer and split the domain package now, without forcing the
acquisition/tree cutover in the same change.

The accepted split is:

- `domain/common.py`
- `domain/events.py`
- `domain/ledger.py`
- `domain/tree.py`
- `domain/gateway.py`

`domain/models.py` remains as a compatibility shim that re-exports the split contracts so the
existing parser, tree, and gateway code keeps working during the migration.

The additive v2 contracts introduced in this phase are:

- canonical acquisition contracts:
  - `CanonicalDocumentLedger`
  - `CanonicalPage`
  - `TextBlock`
  - `LineBlock`
  - `TableArtifact`
  - `VisualArtifact`
  - `UnresolvedRegion`
  - `AcquisitionManifest`
- normalized provenance/event vocabulary:
  - `ExtractionProvenance`
  - `GroundingEvidence`
  - `DocumentEvent`
  - `PageEvent`
  - `TrustTier`
- projection contracts for the later tree cutover:
  - `TreeSynthesisView`
  - `SynthesisPage`
  - `SynthesisLine`
  - `SynthesisTextProjection`
  - `SynthesisUnresolvedRegion`
  - `SynthesisTrustSummary`

## Consequences

- The current Phase 01 parse substrate and Phase 02 tree pipeline remain functional without an
  immediate cutover.
- The repo now has a typed place to land the future native-first acquisition and projection work
  from `major-changes-v2.md`.
- Existing imports from `strataforge.domain.models` remain valid, which keeps the migration
  additive.
- `PageLedgerRow` remains in the codebase for compatibility, but it is no longer the only
  long-term contract surface available for future phases.
