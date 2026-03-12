"""Protocols for the attachment-only multimodal gateway."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from strataforge.llm.multimodal_gateway.types import (
    MultimodalGatewayConfig,
    MultimodalGatewayRequest,
    MultimodalGatewaySuccess,
    ProviderInvocationRequest,
    ProviderInvocationResult,
)

T = TypeVar("T", bound=BaseModel)


class MultimodalProviderAdapter(Protocol):
    """Internal provider boundary for multimodal adapters."""

    provider_name: str

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: MultimodalGatewayConfig,
    ) -> ProviderInvocationResult:
        """Invoke one multimodal request without retries."""


class StructuredMultimodalGateway(Protocol):
    """Public typed multimodal gateway contract."""

    def invoke(self, request: MultimodalGatewayRequest[T]) -> MultimodalGatewaySuccess[T]:
        """Return a validated model or raise a typed multimodal gateway error."""
