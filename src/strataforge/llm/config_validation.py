"""LLM-provider capability validation helpers."""

from __future__ import annotations

from nullvector.llm.errors import GatewayConfigurationError
from nullvector.llm.types import GatewayConfig, OpenAIProviderConfig, StructuredOutputMode


def provider_supported_modes(config: GatewayConfig) -> tuple[StructuredOutputMode, ...]:
    """Return the structured-output modes supported by the configured provider family."""

    if isinstance(config.provider, OpenAIProviderConfig):
        return (StructuredOutputMode.PROVIDER_NATIVE,)
    return (StructuredOutputMode.TRANSPORT_COMPATIBLE,)


def validate_gateway_mode_configuration(config: GatewayConfig) -> None:
    """Reject unsupported provider/mode combinations before the first request is sent."""

    if (
        config.structured_output_mode_preference is not None
        and config.structured_output_mode_preference not in provider_supported_modes(config)
    ):
        msg = (
            f"provider {config.provider.provider} does not support configured structured "
            f"output mode {config.structured_output_mode_preference.value}"
        )
        raise GatewayConfigurationError(msg)


__all__ = ["provider_supported_modes", "validate_gateway_mode_configuration"]
