# Codex Prompt — Phase 03 LLM Gateway (Start Here)

You are working on NullVector.

Mission:
Implement Phase 03 as a production-grade, framework-agnostic LLM gateway that enforces strict typed boundaries, structured outputs, auditable retries, and deterministic failure handling.

Primary architectural rule:
The NullVector core must own:
- request/response contracts
- schema validation
- typed error normalization
- retry and backoff policy
- raw-response audit capture
- redaction hooks
- observability metadata

Do NOT delegate those responsibilities to LangChain, Instructor, Pydantic AI, LiteLLM, or any other framework as the canonical runtime behavior.
Frameworks may be supported later as optional integrations, but not as the core gateway boundary.

Scope for the first Phase 03 implementation:
1. Build the gateway core and contracts
2. Build one real production transport/provider adapter
3. Build one deterministic no-network adapter for tests
4. Add prompt builders for the bounded tree-repair use case first
5. Do not wire summarization into the tree pipeline yet unless required by tests

What to implement

## 1. New package structure

Create a new LLM gateway package under `src/nullvector/llm/` with this shape:

- `__init__.py`
- `types.py`
- `errors.py`
- `protocols.py`
- `audit.py`
- `retry.py`
- `service.py`
- `prompts/`
  - `__init__.py`
  - `repair.py`
  - `verification.py`
  - `summarization.py`
- `providers/`
  - `__init__.py`
  - `noop.py`
  - one real provider/transport adapter
- `integrations/`
  - optional placeholder package only if needed, but do not make frameworks part of the first runtime path

Do not start with framework adapters like `langchain`, `pydantic_ai`, or `instructor` as primary implementations.
If you add placeholders for those, keep them out of the default runtime path.

## 2. Core contracts

Define strict Pydantic models and Protocols for the gateway.

At minimum add:

- `LLMRole`
- `LLMMessage`
- `GatewayConfig`
- `GatewayRequest`
- `GatewayUsage`
- `GatewayAttempt`
- `GatewayAuditRecord`
- `GatewaySuccess[T]`
- `GatewayFailure`
- `RedactionHook` protocol
- `StructuredLLMGateway` protocol

The gateway API must not return raw text to the caller as its primary output.
The public success path must return a validated Pydantic model plus structured metadata.

Use generics where appropriate so the response schema is explicit:
- request carries `response_model: type[T]`
- success carries `output: T`

## 3. Typed failure model

Implement a strict error taxonomy.

Required failure categories:
- validation failure
- timeout
- rate limit
- network failure
- provider refusal
- context length violation
- authentication / authorization failure
- unsupported capability
- unknown provider failure

Expose both:
- typed exception classes for internal control flow
- a typed `GatewayFailure` envelope for persisted/audited results

No silent fallback.
No untyped exceptions crossing the gateway boundary.
No regex JSON repair.
No best-effort coercion after schema failure.

## 4. Retry policy

Implement retry behavior in NullVector, not in third-party frameworks.

Requirements:
- bounded exponential backoff
- retry only for retryable failures
- no retries for validation failure, refusal, auth failure, or context-length violation unless explicitly justified
- every attempt must be recorded
- attempt count, delay, final failure category, and provider metadata must be observable

Put retry policy in `retry.py`, not inside provider adapters.

## 5. Audit and redaction

Implement raw-response audit capture with redaction hooks.

Requirements:
- capture prompt messages sent
- capture raw provider response payload
- capture parsed/validated model payload
- capture failure envelope when applicable
- support redaction before persistence
- support disabling raw capture by config
- do not leak secrets, API keys, or auth headers into audit payloads

The gateway core should produce a `GatewayAuditRecord`.
Persistence can remain filesystem-local for now unless the repo already has a stronger artifact convention to reuse.

## 6. Provider adapter strategy

Implement exactly two adapters first:

### A. `providers/noop.py`
A deterministic no-network adapter for tests.
It must not invent semantically meaningless data.
It should only return outputs for explicit test fixtures / scripted responses.
If a request is not recognized by the test double, fail clearly with a typed unsupported/noop failure.

### B. One real production adapter
Choose one of these:
- a direct provider SDK adapter, or
- an OpenAI-compatible transport adapter, or
- LiteLLM as a transport/router adapter

Decision rule:
Prefer the smallest adapter surface that still lets NullVector own retries, typed error normalization, validation, and auditing.

Do NOT make Instructor or Pydantic AI the first canonical adapter.
They may be added later as integrations, not as the core runtime foundation.

## 7. Structured outputs

Implement schema-driven structured outputs in the gateway core.

Requirements:
- request always includes a target Pydantic model
- provider adapter receives schema information in a provider-appropriate way
- provider response is validated with Pydantic before crossing the boundary
- malformed provider payload must surface as typed validation failure
- raw payload must still be auditable
- when provider-native structured output exists, prefer it
- when it does not, use the narrowest supported structured-output mechanism available without weakening the typed boundary

Do not implement prompt-only “please return JSON” as the only structured-output strategy.
If prompt-based fallback is unavoidable in one adapter, mark it explicitly as lower-assurance in metadata.

## 8. Prompt builders

Implement prompt builders as domain artifacts, not adapter concerns.

Add builders for:
- bounded heading normalization
- verification assistance
- node summarization

However, only wire bounded heading normalization into an actual runtime path in this phase unless more is required for tests.

Prompt builder requirements:
- grounded output only
- explicit output contract
- bounded instructions only
- no permission to invent sections, facts, spans, or provenance
- deterministic temperature defaults

## 9. Phase 02 integration boundary

Integrate only at the repair boundary first.

Extend the existing repair flow so that:
- `NoopRepairEngine` still works and remains the default in tests unless explicitly overridden
- a new gateway-backed repair engine can convert bounded repair requests into typed repair decisions
- repair never bypasses verification
- repair never invents unseen sections or spans

Do not broadly refactor Phase 02 tree logic in this first Phase 03 pass.

## 10. Configuration

Add config models for:
- adapter/provider selection
- model name
- timeout
- retry policy
- structured-output mode preference
- audit capture settings
- redaction settings
- provider-specific extras

Do not use `dict[str, str]` for all extras.
Use a JSON-compatible typed value model or explicit provider config models.

Do not store raw API keys in repository artifacts.
Only store env-var names or indirect references.

## 11. Testing requirements

Add unit tests for:
- schema success path
- malformed payload path
- refusal path
- timeout path
- retry path
- typed validation failure path
- audit record generation
- redaction hook behavior
- retry classification behavior
- noop adapter behavior
- provider error normalization
- no raw untyped output crossing the gateway boundary

Add contract tests with mocked provider responses.
Mock at the transport/provider boundary, not at the Pydantic model boundary.

Add at least one integration-style test proving that a gateway-backed repair engine can process a bounded repair request and emit a typed repair decision without weakening Phase 02 verification.

## 12. Delivery constraints

Do not introduce deprecated APIs.
Do not add framework-heavy runtime dependencies to the core package unless they are strictly necessary.
Keep optional dependencies isolated behind adapter/integration boundaries.
Prefer lazy imports for optional adapters.

Do not claim support for “any SDK/framework” unless there is a stable contract boundary proving it.
The goal of this phase is framework-agnostic core design, not immediate first-party support for every ecosystem package.

## 13. Acceptance criteria

Phase 03 is only complete if all of the following are true:
- the gateway core is independent of any one SDK/framework
- one real adapter works end-to-end
- no-network tests can run through the noop adapter
- all outputs crossing the boundary are validated Pydantic models
- all failures are typed and observable
- retries are owned by NullVector
- raw-response audit capture exists with redaction hooks
- bounded repair prompting is implemented through the new gateway path
- existing Phase 02 behavior remains stable when the noop/default path is used

Validation required before completion:
- `bash .codex/bin/preflight-codex.sh`
- `make format-check`
- `make lint`
- `make typecheck`
- gateway unit tests
- contract tests with mocked provider responses
- full `make test`

Return:
- changed files
- validation output
- adapter chosen for the first real implementation and why
- operational caveats
- residual risks

Status:
- completed on 2026-03-11
- Phase 03 was delivered as a split implementation:
  - `03A`: typed gateway core, deterministic noop adapter, LiteLLM SDK adapter with
    `transport_compatible` assurance only, NullVector-owned retries, typed failures, and redacted
    audit persistence
  - `03B`: direct OpenAI Responses adapter with `provider_native_strict` assurance and bounded
    `GatewayRepairEngine` integration through the existing repair seam
  - `03C`: cross-adapter failure normalization hardening, Phase 03 notebook update, cookbook
    notebook, ADR documentation, and gateway/unit/integration validation coverage
