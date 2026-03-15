"""LiteLLM SDK adapter for structured text and attachment-backed requests."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from nullvector.llm.audit import json_safe
from nullvector.llm.types import (
    GatewayAssuranceMode,
    GatewayConfig,
    GatewayFailureCategory,
    GatewayUsage,
    LiteLLMProviderConfig,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    RegionImageInput,
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


def _extract_structured_output(payload: dict[str, Any]) -> dict[str, Any] | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return None
    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return cast(dict[str, Any], parsed)
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return cast(dict[str, Any], json.loads(content))
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return cast(dict[str, Any], json.loads(text))
    return None


def _guess_media_type(region: RegionImageInput) -> str:
    if region.media_type is not None:
        return region.media_type
    guessed, _ = mimetypes.guess_type(region.image_path)
    return guessed or "image/png"


def _image_data_url(region: RegionImageInput) -> str:
    encoded = base64.b64encode(Path(region.image_path).read_bytes()).decode("ascii")
    return f"data:{_guess_media_type(region)};base64,{encoded}"


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
    if status_code == 400 and ("image" in message_key or "attachment" in message_key):
        category = GatewayFailureCategory.VALIDATION_FAILURE
        retryable = False
    elif "timeout" in exc_name or "timeout" in message_key:
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
    elif "schema" in message_key or "validation" in message_key or "json" in message_key:
        category = GatewayFailureCategory.VALIDATION_FAILURE
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
        raw_request_payload=json_safe(raw_request_payload),
        raw_response_payload=json_safe(getattr(exc, "body", None)),
        status_code=status_code if isinstance(status_code, int) else None,
        provider_error_code=str(provider_error_code) if provider_error_code is not None else None,
    )


class LiteLLMSDKAdapter:
    """LiteLLM SDK adapter constrained to transport-compatible structured output."""

    provider_name = "litellm"

    def __init__(
        self,
        *,
        responses_callable: Callable[..., Any] | None = None,
        completion_callable: Callable[..., Any] | None = None,
        supports_vision_callable: Callable[..., bool] | None = None,
        get_supported_openai_params_callable: Callable[..., Any] | None = None,
    ) -> None:
        self._responses_callable = responses_callable
        self._completion_callable = completion_callable
        self._supports_vision_callable = supports_vision_callable
        self._get_supported_openai_params_callable = get_supported_openai_params_callable

    def _default_responses_callable(self) -> Callable[..., Any]:
        if self._responses_callable is not None:
            return self._responses_callable
        from litellm import responses

        return cast(Callable[..., Any], responses)

    def _default_completion_callable(self) -> Callable[..., Any]:
        if self._completion_callable is not None:
            return self._completion_callable
        from litellm import completion

        return cast(Callable[..., Any], completion)

    def _supports_vision(
        self,
        *,
        model_name: str,
        custom_llm_provider: str | None,
    ) -> bool | None:
        is_openrouter_model = custom_llm_provider == "openrouter" or model_name.startswith(
            "openrouter/"
        )
        try:
            if self._supports_vision_callable is not None:
                advertised = bool(
                    self._supports_vision_callable(
                        model_name,
                        custom_llm_provider=custom_llm_provider,
                    )
                )
            else:
                from litellm import supports_vision

                advertised = bool(
                    supports_vision(
                        model_name,
                        custom_llm_provider=custom_llm_provider,
                    )
                )
        except Exception:
            return None

        if advertised:
            return True
        if is_openrouter_model:
            return None
        return False

    def _supports_response_format(
        self,
        *,
        model_name: str,
        custom_llm_provider: str | None,
    ) -> bool | None:
        try:
            if self._get_supported_openai_params_callable is not None:
                supported_params = self._get_supported_openai_params_callable(
                    model_name,
                    custom_llm_provider=custom_llm_provider,
                    request_type="chat_completion",
                )
            else:
                from litellm import get_supported_openai_params

                supported_params = get_supported_openai_params(
                    model_name,
                    custom_llm_provider=custom_llm_provider,
                    request_type="chat_completion",
                )
        except Exception:
            return None

        if supported_params is None:
            return None
        if isinstance(supported_params, dict):
            return "response_format" in supported_params
        if isinstance(supported_params, list | tuple | set):
            return "response_format" in supported_params
        return None

    def _text_call_kwargs(
        self,
        request: ProviderInvocationRequest,
        provider: LiteLLMProviderConfig,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
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

        api_key = provider.api_key
        if api_key is None and provider.api_key_env_var is not None:
            api_key = os.getenv(provider.api_key_env_var)
        if api_key is not None:
            call_kwargs["api_key"] = api_key

        api_base = provider.api_base
        if api_base is None and provider.api_base_env_var is not None:
            api_base = os.getenv(provider.api_base_env_var)
        if api_base is not None:
            call_kwargs["base_url"] = api_base

        api_version = provider.api_version
        if api_version is None and provider.api_version_env_var is not None:
            api_version = os.getenv(provider.api_version_env_var)
        if api_version is not None:
            call_kwargs["api_version"] = api_version

        raw_request_payload.update(provider.extra_body)
        call_kwargs.update(provider.extra_body)
        return raw_request_payload, call_kwargs

    def _invoke_text(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
        provider: LiteLLMProviderConfig,
    ) -> ProviderInvocationResult:
        raw_request_payload, call_kwargs = self._text_call_kwargs(request, provider)
        try:
            response = self._default_responses_callable()(
                timeout=config.timeout_seconds,
                **call_kwargs,
            )
        except Exception as exc:
            return ProviderInvocationResult(
                failure=_normalize_exception(
                    exc,
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    structured_output_mode=request.structured_output_mode,
                    raw_request_payload=raw_request_payload,
                )
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
            )
        )

    def _invoke_with_attachments(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
        provider: LiteLLMProviderConfig,
    ) -> ProviderInvocationResult:
        custom_llm_provider = provider.extra_body.get("custom_llm_provider")
        provider_name = str(custom_llm_provider) if isinstance(custom_llm_provider, str) else None
        vision_supported = self._supports_vision(
            model_name=request.model_name,
            custom_llm_provider=provider_name,
        )
        if vision_supported is False:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="configured LiteLLM model does not advertise vision support",
                    retryable=False,
                )
            )
        response_format_supported = self._supports_response_format(
            model_name=request.model_name,
            custom_llm_provider=provider_name,
        )
        if response_format_supported is False:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="configured LiteLLM model does not advertise response_format support",
                    retryable=False,
                )
            )

        prompt_text = "\n\n".join(message.content for message in request.messages)
        raw_request_payload: dict[str, Any] = {
            "model": request.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        *(
                            {
                                "type": "image_url",
                                "image_url": {"url": _image_data_url(attachment)},
                            }
                            for attachment in request.attachments
                        ),
                    ],
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.response_schema_name,
                    "schema": request.response_schema,
                    "strict": True,
                },
            },
        }
        if request.temperature is not None:
            raw_request_payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            raw_request_payload["max_tokens"] = request.max_output_tokens

        call_kwargs = dict(raw_request_payload)
        api_key = provider.api_key
        if api_key is None and provider.api_key_env_var is not None:
            api_key = os.getenv(provider.api_key_env_var)
        if api_key is not None:
            call_kwargs["api_key"] = api_key
        if provider.api_base is not None:
            call_kwargs["base_url"] = provider.api_base
        elif provider.api_base_env_var is not None:
            api_base = os.getenv(provider.api_base_env_var)
            if api_base is not None:
                call_kwargs["base_url"] = api_base
        if provider.api_version is not None:
            call_kwargs["api_version"] = provider.api_version
        elif provider.api_version_env_var is not None:
            api_version = os.getenv(provider.api_version_env_var)
            if api_version is not None:
                call_kwargs["api_version"] = api_version
        raw_request_payload.update(provider.extra_body)
        call_kwargs.update(provider.extra_body)

        try:
            response = self._default_completion_callable()(
                timeout=config.timeout_seconds,
                **call_kwargs,
            )
        except Exception as exc:
            return ProviderInvocationResult(
                failure=_normalize_exception(
                    exc,
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    structured_output_mode=request.structured_output_mode,
                    raw_request_payload=raw_request_payload,
                )
            )

        payload = _extract_response_json(response)
        try:
            structured_output = _extract_structured_output(payload)
        except Exception as exc:
            return ProviderInvocationResult(
                failure=_normalize_exception(
                    exc,
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    structured_output_mode=request.structured_output_mode,
                    raw_request_payload=raw_request_payload,
                )
            )

        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name=self.provider_name,
                model_name=request.model_name,
                assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                raw_request_payload=json_safe(raw_request_payload),
                raw_response_payload=json_safe(payload),
                structured_output_json=structured_output,
                usage=_extract_usage(payload),
                status_code=200,
                provider_response_id=(
                    str(payload.get("id")) if payload.get("id") is not None else None
                ),
            )
        )

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
                )
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
                )
            )

        if request.attachments:
            return self._invoke_with_attachments(request, config, provider)
        return self._invoke_text(request, config, provider)


__all__ = ["LiteLLMSDKAdapter"]
