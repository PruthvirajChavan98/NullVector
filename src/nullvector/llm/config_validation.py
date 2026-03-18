"""LLM-provider capability validation helpers."""

from __future__ import annotations

from nullvector.llm.errors import GatewayConfigurationError
from nullvector.llm.types import GatewayConfig, StructuredOutputMode


def provider_supported_modes(config: GatewayConfig) -> tuple[StructuredOutputMode, ...]:
    """Return the structured-output modes declared in the gateway configuration."""

    return config.supported_structured_output_modes


def validate_gateway_mode_configuration(config: GatewayConfig) -> None:
    """Reject unsupported mode preferences before the first request is sent."""

    if (
        config.structured_output_mode_preference is not None
        and config.structured_output_mode_preference not in provider_supported_modes(config)
    ):
        msg = (
            f"configured provider does not support structured output mode "
            f"{config.structured_output_mode_preference.value}"
        )
        raise GatewayConfigurationError(msg)


__all__ = ["provider_supported_modes", "validate_gateway_mode_configuration"]
