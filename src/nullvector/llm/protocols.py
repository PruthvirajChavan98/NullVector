"""Protocols for the Phase 03 LLM gateway."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from nullvector.llm.types import (
    GatewayAuditRecord,
    GatewayConfig,
    GatewayRequest,
    GatewaySuccess,
    ProviderInvocationRequest,
    ProviderInvocationResult,
)

T = TypeVar("T", bound=BaseModel)


class RedactionHook(Protocol):
    """Protocol for audit-record redaction before persistence."""

    def redact(self, record: GatewayAuditRecord) -> GatewayAuditRecord:
        """Return a redacted audit record."""


class ProviderAdapter(Protocol):
    """Internal provider boundary owned by NullVector."""

    provider_name: str

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        """Invoke a single structured provider call without retries."""


class StructuredLLMGateway(Protocol):
    """Public typed gateway contract."""

    def invoke(self, request: GatewayRequest[T]) -> GatewaySuccess[T]:
        """Return a validated model or raise a typed gateway exception."""
