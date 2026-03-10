# Codex Prompt — Phase 03 LLM Gateway

You are working on StrataForge.

Mission:
Implement a production LLM gateway with strict structured outputs and typed failure modes.

Objectives:
1. create a provider-agnostic gateway interface
2. create a concrete provider adapter
3. implement schema-driven structured outputs
4. validate all responses into Pydantic models
5. implement typed error envelopes for:
   - validation failure
   - timeout
   - rate limit
   - network failure
   - provider refusal
   - context-length violation
6. implement retry policy with bounded exponential backoff
7. implement raw-response audit capture with redaction hooks
8. implement prompt builders for:
   - bounded heading normalization
   - node summarization
   - verification assistance

Rules:
- no regex JSON repair
- no untyped model output crosses the gateway boundary
- no silent fallback on parse failure
- all retries and failures must be observable
- prompts must request grounded output only

Required tests:
- schema success path
- malformed payload path
- refusal path
- timeout path
- retry path
- typed validation failure path

Validation required before completion:
- formatter check
- lint
- type-check
- gateway unit tests
- contract tests with mocked provider responses

Return:
- changed files
- validation output
- operational caveats

