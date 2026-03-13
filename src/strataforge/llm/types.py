"""Strict typed contracts for the Phase 03 LLM gateway."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    model_validator,
)
from pydantic import (
    JsonValue as PydanticJsonValue,
)

from nullvector.domain.models import NonEmptyStr, StrataModel

T = TypeVar("T", bound=BaseModel)
JSONValue = PydanticJsonValue


class LLMRole(StrEnum):
    """Supported structured LLM message roles."""

    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"
    ASSISTANT = "assistant"


class StructuredOutputMode(StrEnum):
    """Requested structured-output strategy for an invocation."""

    TRANSPORT_COMPATIBLE = "transport_compatible"
    PROVIDER_NATIVE = "provider_native"


class GatewayAssuranceMode(StrEnum):
    """Assurance level actually delivered by a provider adapter."""

    TRANSPORT_COMPATIBLE = "transport_compatible"
    PROVIDER_NATIVE_STRICT = "provider_native_strict"


class GatewayFailureCategory(StrEnum):
    """Typed failure taxonomy enforced at the gateway boundary."""

    VALIDATION_FAILURE = "validation_failure"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    NETWORK_FAILURE = "network_failure"
    PROVIDER_REFUSAL = "provider_refusal"
    CONTEXT_LENGTH_VIOLATION = "context_length_violation"
    AUTH_FAILURE = "auth_failure"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNKNOWN_PROVIDER_FAILURE = "unknown_provider_failure"


class LLMMessage(StrataModel):
    """Single structured prompt message."""

    role: LLMRole
    content: NonEmptyStr


class GatewayRetryPolicy(StrataModel):
    """Retry policy owned by NullVector, not by provider SDKs."""

    max_attempts: PositiveInt = 3
    initial_backoff_seconds: PositiveFloat = 0.25
    backoff_multiplier: PositiveFloat = 2.0
    max_backoff_seconds: PositiveFloat = 2.0


class GatewayAuditConfig(StrataModel):
    """Audit capture and persistence controls."""

    persist_root: NonEmptyStr | None = None
    capture_raw_request: bool = True
    capture_raw_response: bool = True


class LiteLLMProviderConfig(StrataModel):
    """Config for the LiteLLM SDK adapter."""

    provider: NonEmptyStr = "litellm"
    model: NonEmptyStr
    api_key: NonEmptyStr | None = None
    api_base: NonEmptyStr | None = None
    api_version: NonEmptyStr | None = None
    api_key_env_var: NonEmptyStr | None = None
    api_base_env_var: NonEmptyStr | None = None
    api_version_env_var: NonEmptyStr | None = None
    extra_body: dict[str, JSONValue] = Field(default_factory=dict)


class OpenAIProviderConfig(StrataModel):
    """Config for the direct OpenAI Responses API adapter."""

    provider: NonEmptyStr = "openai_http"
    model: NonEmptyStr
    api_key_env_var: NonEmptyStr = "OPENAI_API_KEY"
    base_url: NonEmptyStr = "https://api.openai.com/v1"
    organization_env_var: NonEmptyStr | None = None
    project_env_var: NonEmptyStr | None = None
    extra_body: dict[str, JSONValue] = Field(default_factory=dict)


ProviderConfig = LiteLLMProviderConfig | OpenAIProviderConfig


class GatewayConfig(StrataModel):
    """Gateway-level configuration and provider selection."""

    provider: ProviderConfig
    timeout_seconds: PositiveFloat = 30.0
    retry_policy: GatewayRetryPolicy = Field(default_factory=GatewayRetryPolicy)
    audit: GatewayAuditConfig = Field(default_factory=GatewayAuditConfig)
    structured_output_mode_preference: StructuredOutputMode | None = None


class GatewayRequest(StrataModel, Generic[T]):
    """Single structured request against the gateway."""

    operation_name: NonEmptyStr
    messages: tuple[LLMMessage, ...]
    response_model: type[T] = Field(exclude=True, repr=False)
    model_name: NonEmptyStr | None = None
    temperature: NonNegativeFloat | None = 0.0
    max_output_tokens: PositiveInt | None = None
    metadata: dict[str, JSONValue] = Field(default_factory=dict)
    idempotency_key: NonEmptyStr | None = None
    structured_output_mode: StructuredOutputMode | None = None

    @model_validator(mode="after")
    def validate_request(self) -> GatewayRequest[T]:
        if not self.messages:
            msg = "gateway requests must include at least one message"
            raise ValueError(msg)
        if self.temperature is not None and self.temperature > 2:
            msg = "temperature must be less than or equal to 2"
            raise ValueError(msg)
        return self


class GatewayUsage(StrataModel):
    """Normalized token usage accounting."""

    input_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0
    total_tokens: NonNegativeInt = 0

    @model_validator(mode="after")
    def validate_total(self) -> GatewayUsage:
        if self.total_tokens not in (0, self.input_tokens + self.output_tokens):
            msg = "total_tokens must be zero or equal input_tokens + output_tokens"
            raise ValueError(msg)
        if self.total_tokens == 0:
            return self.model_copy(
                update={"total_tokens": self.input_tokens + self.output_tokens},
            )
        return self


class GatewayAttempt(StrataModel):
    """One observable gateway attempt."""

    attempt_number: PositiveInt
    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: GatewayAssuranceMode
    structured_output_mode: StructuredOutputMode
    delay_before_attempt_seconds: NonNegativeFloat = 0.0
    started_at: datetime
    completed_at: datetime
    usage: GatewayUsage | None = None
    failure_category: GatewayFailureCategory | None = None
    failure_message: NonEmptyStr | None = None
    retryable: bool = False
    status_code: int | None = None
    provider_request_id: NonEmptyStr | None = None
    provider_response_id: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> GatewayAttempt:
        if self.completed_at < self.started_at:
            msg = "completed_at must be greater than or equal to started_at"
            raise ValueError(msg)
        return self


class GatewayFailure(StrataModel):
    """Typed failure envelope persisted and surfaced by the gateway."""

    request_id: NonEmptyStr
    operation_name: NonEmptyStr
    category: GatewayFailureCategory
    message: NonEmptyStr
    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: GatewayAssuranceMode
    structured_output_mode: StructuredOutputMode
    retryable: bool
    attempt_count: NonNegativeInt
    status_code: int | None = None
    provider_request_id: NonEmptyStr | None = None
    provider_response_id: NonEmptyStr | None = None
    provider_error_code: NonEmptyStr | None = None
    details: dict[str, JSONValue] = Field(default_factory=dict)


class GatewaySuccess(StrataModel, Generic[T]):
    """Validated success payload returned across the public boundary."""

    request_id: NonEmptyStr
    operation_name: NonEmptyStr
    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: GatewayAssuranceMode
    structured_output_mode: StructuredOutputMode
    output: T
    attempts: tuple[GatewayAttempt, ...]
    usage: GatewayUsage | None = None
    provider_request_id: NonEmptyStr | None = None
    provider_response_id: NonEmptyStr | None = None
    audit_path: NonEmptyStr | None = None


class GatewayAuditRecord(StrataModel):
    """Redacted, persistable gateway audit artifact."""

    audit_id: NonEmptyStr
    request_id: NonEmptyStr
    operation_name: NonEmptyStr
    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: GatewayAssuranceMode
    structured_output_mode: StructuredOutputMode
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    messages: tuple[LLMMessage, ...]
    request_payload: JSONValue | None = None
    response_payload: JSONValue | None = None
    parsed_output: JSONValue | None = None
    failure: GatewayFailure | None = None
    attempts: tuple[GatewayAttempt, ...]
    metadata: dict[str, JSONValue] = Field(default_factory=dict)


class GatewayOutcome(StrataModel, Generic[T]):
    """Internal unified result object produced before invoke() raises or returns."""

    success: GatewaySuccess[T] | None = None
    failure: GatewayFailure | None = None
    audit_record: GatewayAuditRecord
    audit_path: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> GatewayOutcome[T]:
        if (self.success is None) == (self.failure is None):
            msg = "exactly one of success or failure must be present"
            raise ValueError(msg)
        return self


class ProviderInvocationRequest(StrataModel):
    """JSON-safe request passed to provider adapters."""

    request_id: NonEmptyStr
    operation_name: NonEmptyStr
    messages: tuple[LLMMessage, ...]
    model_name: NonEmptyStr
    structured_output_mode: StructuredOutputMode
    response_model_name: NonEmptyStr
    response_schema_name: NonEmptyStr
    response_schema: dict[str, JSONValue]
    timeout_seconds: PositiveFloat
    temperature: NonNegativeFloat | None = 0.0
    max_output_tokens: PositiveInt | None = None
    metadata: dict[str, JSONValue] = Field(default_factory=dict)
    idempotency_key: NonEmptyStr | None = None


class ProviderInvocationSuccess(StrataModel):
    """Normalized successful provider response before Pydantic validation."""

    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: GatewayAssuranceMode
    structured_output_mode: StructuredOutputMode
    raw_request_payload: JSONValue | None = None
    raw_response_payload: JSONValue | None = None
    structured_output_json: JSONValue | None = None
    structured_output_text: NonEmptyStr | None = None
    usage: GatewayUsage | None = None
    status_code: int | None = None
    provider_request_id: NonEmptyStr | None = None
    provider_response_id: NonEmptyStr | None = None


class ProviderInvocationFailure(StrataModel):
    """Normalized provider failure before retry/audit handling."""

    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: GatewayAssuranceMode
    structured_output_mode: StructuredOutputMode
    category: GatewayFailureCategory
    message: NonEmptyStr
    retryable: bool
    raw_request_payload: JSONValue | None = None
    raw_response_payload: JSONValue | None = None
    status_code: int | None = None
    provider_request_id: NonEmptyStr | None = None
    provider_response_id: NonEmptyStr | None = None
    provider_error_code: NonEmptyStr | None = None
    details: dict[str, JSONValue] = Field(default_factory=dict)


class ProviderInvocationResult(StrataModel):
    """Exactly-one wrapper around normalized provider results."""

    success: ProviderInvocationSuccess | None = None
    failure: ProviderInvocationFailure | None = None

    @model_validator(mode="after")
    def validate_result(self) -> ProviderInvocationResult:
        if (self.success is None) == (self.failure is None):
            msg = "exactly one of success or failure must be present"
            raise ValueError(msg)
        return self
