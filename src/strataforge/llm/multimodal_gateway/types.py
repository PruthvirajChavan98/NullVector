"""Typed contracts for the attachment-only multimodal gateway."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, NonNegativeInt, PositiveFloat, model_validator
from pydantic import JsonValue as PydanticJsonValue

from strataforge.domain.models import (
    NonEmptyStr,
    StrataModel,
    StructuredRegionInsight,
    VisualRegionReference,
)

T = TypeVar("T", bound=BaseModel)
JSONValue = PydanticJsonValue


class MultimodalAssuranceMode(StrEnum):
    """Assurance level for attachment-only multimodal enrichment."""

    ATTACHMENT_ONLY = "attachment_only"


class MultimodalFailureCategory(StrEnum):
    """Typed multimodal failure taxonomy."""

    VALIDATION_FAILURE = "validation_failure"
    INVALID_ATTACHMENT = "invalid_attachment"
    TIMEOUT = "timeout"
    NETWORK_FAILURE = "network_failure"
    AUTH_FAILURE = "auth_failure"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNKNOWN_PROVIDER_FAILURE = "unknown_provider_failure"


class RegionImageInput(StrataModel):
    """Explicit region/image payload for multimodal interpretation."""

    region: VisualRegionReference
    image_path: NonEmptyStr
    media_type: NonEmptyStr | None = None


class MultimodalProviderConfig(StrataModel):
    """Provider configuration for multimodal adapters."""

    provider: NonEmptyStr = "multimodal_noop"
    model: NonEmptyStr
    api_key_env_var: NonEmptyStr | None = None
    extra_body: dict[str, JSONValue] = Field(default_factory=dict)


class MultimodalGatewayConfig(StrataModel):
    """Gateway-level configuration for multimodal enrichment."""

    provider: MultimodalProviderConfig
    timeout_seconds: PositiveFloat = 30.0
    audit_root: NonEmptyStr | None = None


class MultimodalGatewayRequest(StrataModel, Generic[T]):
    """Single typed multimodal request."""

    operation_name: NonEmptyStr
    prompt: NonEmptyStr
    regions: tuple[RegionImageInput, ...]
    response_model: type[T] = Field(exclude=True, repr=False)
    model_name: NonEmptyStr | None = None
    metadata: dict[str, JSONValue] = Field(default_factory=dict)
    idempotency_key: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_regions(self) -> MultimodalGatewayRequest[T]:
        if not self.regions:
            msg = "multimodal requests must include at least one region"
            raise ValueError(msg)
        return self


class MultimodalUsage(StrataModel):
    """Normalized multimodal usage accounting."""

    input_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0
    total_tokens: NonNegativeInt = 0

    @model_validator(mode="after")
    def validate_total(self) -> MultimodalUsage:
        computed_total = self.input_tokens + self.output_tokens
        if self.total_tokens not in (0, computed_total):
            msg = "total_tokens must be zero or equal input_tokens + output_tokens"
            raise ValueError(msg)
        if self.total_tokens == 0:
            return self.model_copy(update={"total_tokens": computed_total})
        return self


class MultimodalGatewayFailure(StrataModel):
    """Typed failure envelope for multimodal operations."""

    request_id: NonEmptyStr
    operation_name: NonEmptyStr
    category: MultimodalFailureCategory
    message: NonEmptyStr
    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: MultimodalAssuranceMode
    status_code: int | None = None
    details: dict[str, JSONValue] = Field(default_factory=dict)


class MultimodalGatewaySuccess(StrataModel, Generic[T]):
    """Validated success payload returned across the multimodal gateway boundary."""

    request_id: NonEmptyStr
    operation_name: NonEmptyStr
    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: MultimodalAssuranceMode
    output: T
    usage: MultimodalUsage | None = None
    audit_path: NonEmptyStr | None = None


class MultimodalGatewayAuditRecord(StrataModel):
    """Persistable audit payload for multimodal requests."""

    audit_id: NonEmptyStr
    request_id: NonEmptyStr
    operation_name: NonEmptyStr
    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: MultimodalAssuranceMode
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    prompt: NonEmptyStr
    regions: tuple[RegionImageInput, ...]
    response_payload: JSONValue | None = None
    parsed_output: JSONValue | None = None
    failure: MultimodalGatewayFailure | None = None
    metadata: dict[str, JSONValue] = Field(default_factory=dict)


class ProviderInvocationRequest(StrataModel):
    """Normalized provider request for multimodal adapters."""

    request_id: NonEmptyStr
    operation_name: NonEmptyStr
    prompt: NonEmptyStr
    regions: tuple[RegionImageInput, ...]
    model_name: NonEmptyStr
    response_model_name: NonEmptyStr
    response_schema: dict[str, JSONValue]
    metadata: dict[str, JSONValue] = Field(default_factory=dict)
    idempotency_key: NonEmptyStr | None = None


class ProviderInvocationSuccess(StrataModel):
    """Normalized multimodal provider success before validation."""

    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: MultimodalAssuranceMode
    raw_response_payload: JSONValue | None = None
    structured_output_json: JSONValue | None = None
    usage: MultimodalUsage | None = None
    status_code: int | None = None


class ProviderInvocationFailure(StrataModel):
    """Normalized multimodal provider failure before audit handling."""

    provider_name: NonEmptyStr
    model_name: NonEmptyStr
    assurance_mode: MultimodalAssuranceMode
    category: MultimodalFailureCategory
    message: NonEmptyStr
    status_code: int | None = None
    raw_response_payload: JSONValue | None = None
    details: dict[str, JSONValue] = Field(default_factory=dict)


class ProviderInvocationResult(StrataModel):
    """Exactly-one wrapper around provider invocation results."""

    success: ProviderInvocationSuccess | None = None
    failure: ProviderInvocationFailure | None = None

    @model_validator(mode="after")
    def validate_result(self) -> ProviderInvocationResult:
        if (self.success is None) == (self.failure is None):
            msg = "exactly one of success or failure must be present"
            raise ValueError(msg)
        return self


class VisualInsightResponse(StrataModel):
    """Default structured multimodal output used by the attachment service."""

    insight: StructuredRegionInsight


__all__ = [
    "JSONValue",
    "MultimodalAssuranceMode",
    "MultimodalFailureCategory",
    "MultimodalGatewayAuditRecord",
    "MultimodalGatewayConfig",
    "MultimodalGatewayFailure",
    "MultimodalGatewayRequest",
    "MultimodalGatewaySuccess",
    "MultimodalProviderConfig",
    "MultimodalUsage",
    "ProviderInvocationFailure",
    "ProviderInvocationRequest",
    "ProviderInvocationResult",
    "ProviderInvocationSuccess",
    "RegionImageInput",
    "VisualInsightResponse",
]
