# ADR 0004: Split LLM Gateway with Transport-Compatible LiteLLM and Provider-Native OpenAI Strict Path

- Status: accepted
- Date: 2026-03-11

## Context

Phase 03 needs a typed LLM gateway that keeps the core NullVector contract independent from any
single SDK while still landing one practical compatibility adapter and one provider-native strict
reference path. The gateway must preserve strict schema validation, typed failures, audit capture,
and bounded repair integration without allowing third-party frameworks to define the canonical
runtime behavior.

## Decision

Implement the Phase 03 LLM gateway in three subphases:

- `03A`: gateway core, deterministic noop adapter, and LiteLLM Python SDK adapter with
  `transport_compatible` assurance only
- `03B`: direct OpenAI Responses API adapter with `provider_native_strict` assurance and bounded
  repair integration through the existing `RepairEngine` protocol
- `03C`: failure normalization hardening, audit stabilization, docs, and notebook closeout

NullVector owns:

- request and response contracts
- JSON Schema generation from Pydantic models
- runtime Pydantic validation
- retry and backoff policy
- typed failure normalization
- redaction hooks and audit persistence

The LiteLLM proxy/server path is explicitly out of scope for Phase 03. The direct OpenAI adapter
targets the Responses API structured-output surface, not Chat Completions compatibility mode.

## Consequences

- Phase 03 can start with a practical compatibility adapter without overstating its assurance
  guarantees.
- The direct OpenAI adapter provides a provider-native strict reference path while keeping the core
  gateway adapter-pluggable for future strict adapters.
- Cookbook-only live provider probes may exist for transport observation, but they do not count as
  validated structured-output support unless they return schema-valid output under audit.
- Audit capture is guaranteed before public exceptions cross the gateway boundary, which keeps
  failure analysis observable and replayable.
- The bounded repair path can use validated LLM output without weakening Phase 02 verification.
- Live provider examples remain optional and env-gated; deterministic noop and mocked examples are
  the default validation path.
