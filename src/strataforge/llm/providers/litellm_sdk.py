"""LiteLLM SDK adapter with transport-compatible assurance only."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, cast

from strataforge.llm.audit import json_safe
from strataforge.llm.types import (
    GatewayAssuranceMode,
    GatewayConfig,
    GatewayFailureCategory,
    GatewayUsage,
    LiteLLMProviderConfig,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    StructuredOutputMode,
)


def _extract_response_json(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return cast(dict[str, Any], value.model_dump())
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    if hasattr(value, "__dict__"):
        return cast(dict[str, Any], vars(value))
    return {"raw": str(value)}


def _extract_output_text(payload: dict[str, Any]) -> str | None:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    for item in cast(list[Any], payload.get("output", [])):
        if isinstance(item, dict):
            for content in cast(list[Any], item.get("content", [])):
                if isinstance(content, dict):
                    text = content.get("text")
                    if isinstance(text, str) and text.strip():
                        return text
    return None


def _extract_usage(payload: dict[str, Any]) -> GatewayUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)
    if not all(isinstance(value, int) for value in (input_tokens, output_tokens, total_tokens)):
        return None
    return GatewayUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _normalize_exception(
    exc: Exception,
    *,
    provider_name: str,
    model_name: str,
    structured_output_mode: StructuredOutputMode,
    raw_request_payload: dict[str, Any],
) -> ProviderInvocationFailure:
    message = str(exc).strip() or exc.__class__.__name__
    status_code = getattr(exc, "status_code", None)
    provider_error_code = getattr(exc, "code", None)
    exc_name = exc.__class__.__name__.casefold()
    message_key = message.casefold()

    category = GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE
    retryable = True
    if "timeout" in exc_name or "timeout" in message_key:
        category = GatewayFailureCategory.TIMEOUT
    elif status_code == 429 or "ratelimit" in exc_name or "rate limit" in message_key:
        category = GatewayFailureCategory.RATE_LIMIT
    elif status_code in (401, 403) or "auth" in exc_name or "permission" in message_key:
        category = GatewayFailureCategory.AUTH_FAILURE
        retryable = False
    elif "context" in message_key and "length" in message_key:
        category = GatewayFailureCategory.CONTEXT_LENGTH_VIOLATION
        retryable = False
    elif "refusal" in message_key or "content filter" in message_key:
        category = GatewayFailureCategory.PROVIDER_REFUSAL
        retryable = False
    elif "connection" in exc_name or "network" in exc_name or "apierror" in exc_name:
        category = GatewayFailureCategory.NETWORK_FAILURE
    elif "unsupported" in message_key or "not implemented" in message_key:
        category = GatewayFailureCategory.UNSUPPORTED_CAPABILITY
        retryable = False

    if category in {
        GatewayFailureCategory.VALIDATION_FAILURE,
        GatewayFailureCategory.PROVIDER_REFUSAL,
        GatewayFailureCategory.AUTH_FAILURE,
        GatewayFailureCategory.CONTEXT_LENGTH_VIOLATION,
        GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
    }:
        retryable = False

    return ProviderInvocationFailure(
        provider_name=provider_name,
        model_name=model_name,
        assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
        structured_output_mode=structured_output_mode,
        category=category,
        message=message,
        retryable=retryable,
        raw_request_payload=raw_request_payload,
        raw_response_payload=json_safe(getattr(exc, "body", None)),
        status_code=status_code if isinstance(status_code, int) else None,
        provider_error_code=str(provider_error_code) if provider_error_code is not None else None,
    )


class LiteLLMSDKAdapter:
    """LiteLLM SDK adapter constrained to the responses-style path."""

    provider_name = "litellm"

    def __init__(
        self,
        *,
        responses_callable: Callable[..., Any] | None = None,
    ) -> None:
        self._responses_callable = responses_callable

    def _default_responses_callable(self) -> Callable[..., Any]:
        if self._responses_callable is not None:
            return self._responses_callable
        from litellm import responses

        return cast(Callable[..., Any], responses)

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        provider = config.provider
        if not isinstance(provider, LiteLLMProviderConfig):
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="LiteLLM adapter requires LiteLLMProviderConfig",
                    retryable=False,
                    raw_request_payload=request.model_dump(mode="json"),
                ),
            )
        if request.structured_output_mode != StructuredOutputMode.TRANSPORT_COMPATIBLE:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
                    message=(
                        "LiteLLM adapter only supports transport-compatible assurance in Phase 03"
                    ),
                    retryable=False,
                    raw_request_payload=request.model_dump(mode="json"),
                ),
            )

        raw_request_payload: dict[str, Any] = {
            "model": request.model_name,
            "input": [message.model_dump(mode="json") for message in request.messages],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.response_schema_name,
                    "schema": request.response_schema,
                    "strict": True,
                },
            },
        }
        if request.temperature is not None:
            raw_request_payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            raw_request_payload["max_output_tokens"] = request.max_output_tokens
        call_kwargs = dict(raw_request_payload)
        if provider.api_key_env_var is not None:
            api_key = os.getenv(provider.api_key_env_var)
            if api_key is not None:
                call_kwargs["api_key"] = api_key
        if provider.api_base_env_var is not None:
            base_url = os.getenv(provider.api_base_env_var)
            if base_url is not None:
                call_kwargs["base_url"] = base_url
        if provider.api_version_env_var is not None:
            api_version = os.getenv(provider.api_version_env_var)
            if api_version is not None:
                call_kwargs["api_version"] = api_version
        raw_request_payload.update(provider.extra_body)
        call_kwargs.update(provider.extra_body)

        try:
            response = self._default_responses_callable()(
                timeout=config.timeout_seconds,
                **call_kwargs,
            )
        except Exception as exc:  # pragma: no cover - exercised via mocked exceptions
            return ProviderInvocationResult(
                failure=_normalize_exception(
                    exc,
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    structured_output_mode=request.structured_output_mode,
                    raw_request_payload=raw_request_payload,
                ),
            )

        payload = _extract_response_json(response)
        output_text = _extract_output_text(payload)
        usage = _extract_usage(payload)
        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name=self.provider_name,
                model_name=request.model_name,
                assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                raw_request_payload=json_safe(raw_request_payload),
                raw_response_payload=json_safe(payload),
                structured_output_text=output_text,
                usage=usage,
                status_code=200,
                provider_response_id=(
                    str(payload.get("id")) if payload.get("id") is not None else None
                ),
            ),
        )
