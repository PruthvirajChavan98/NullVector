"""LiteLLM-backed multimodal adapter for attachment-only enrichment."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from nullvector.llm.audit import json_safe
from nullvector.llm.multimodal_gateway.types import (
    MultimodalAssuranceMode,
    MultimodalFailureCategory,
    MultimodalGatewayConfig,
    MultimodalUsage,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    RegionImageInput,
)


def _extract_response_json(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return cast(dict[str, Any], value.model_dump())
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    if hasattr(value, "__dict__"):
        return cast(dict[str, Any], vars(value))
    return {"raw": str(value)}


def _guess_media_type(region: RegionImageInput) -> str:
    if region.media_type is not None:
        return region.media_type
    guessed, _ = mimetypes.guess_type(region.image_path)
    return guessed or "image/png"


def _image_data_url(region: RegionImageInput) -> str:
    path = Path(region.image_path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{_guess_media_type(region)};base64,{encoded}"


def _extract_usage(payload: dict[str, Any]) -> MultimodalUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)
    if not all(isinstance(value, int) for value in (input_tokens, output_tokens, total_tokens)):
        return None
    return MultimodalUsage(
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


def _normalize_exception(
    exc: Exception,
    *,
    provider_name: str,
    model_name: str,
) -> ProviderInvocationFailure:
    message = str(exc).strip() or exc.__class__.__name__
    status_code = getattr(exc, "status_code", None)
    exc_name = exc.__class__.__name__.casefold()
    message_key = message.casefold()

    category = MultimodalFailureCategory.UNKNOWN_PROVIDER_FAILURE
    if status_code == 400 and ("image" in message_key or "attachment" in message_key):
        category = MultimodalFailureCategory.INVALID_ATTACHMENT
    elif "timeout" in exc_name or "timeout" in message_key:
        category = MultimodalFailureCategory.TIMEOUT
    elif status_code in (401, 403) or "auth" in exc_name or "permission" in message_key:
        category = MultimodalFailureCategory.AUTH_FAILURE
    elif "connection" in exc_name or "network" in exc_name or "apierror" in exc_name:
        category = MultimodalFailureCategory.NETWORK_FAILURE
    elif "unsupported" in message_key or "not implemented" in message_key:
        category = MultimodalFailureCategory.UNSUPPORTED_CAPABILITY
    elif "schema" in message_key or "validation" in message_key or "json" in message_key:
        category = MultimodalFailureCategory.VALIDATION_FAILURE

    return ProviderInvocationFailure(
        provider_name=provider_name,
        model_name=model_name,
        assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
        category=category,
        message=message,
        status_code=status_code if isinstance(status_code, int) else None,
        raw_response_payload=json_safe(getattr(exc, "body", None)),
    )


class LiteLLMMultimodalAdapter:
    """LiteLLM adapter that sends prompt plus persisted images to a vision-capable model."""

    provider_name = "litellm_multimodal"

    def __init__(
        self,
        *,
        completion_callable: Callable[..., Any] | None = None,
        supports_vision_callable: Callable[..., bool] | None = None,
        get_supported_openai_params_callable: Callable[..., Any] | None = None,
    ) -> None:
        self._completion_callable = completion_callable
        self._supports_vision_callable = supports_vision_callable
        self._get_supported_openai_params_callable = get_supported_openai_params_callable

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
            # LiteLLM's OpenRouter model metadata can lag behind the actual routed model
            # capabilities, so a negative probe is treated as inconclusive and the real
            # provider request becomes the source of truth. This applies both to explicit
            # custom-provider routing and to openrouter/... model aliases.
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

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: MultimodalGatewayConfig,
    ) -> ProviderInvocationResult:
        if config.provider.provider != self.provider_name:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                    category=MultimodalFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="LiteLLM multimodal adapter requires provider='litellm_multimodal'",
                )
        )

        custom_llm_provider = config.provider.extra_body.get("custom_llm_provider")
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
                    assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                    category=MultimodalFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="configured LiteLLM model does not advertise vision support",
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
                    assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                    category=MultimodalFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="configured LiteLLM model does not advertise response_format support",
                )
            )

        messages: list[dict[str, object]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": request.prompt},
                    *(
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_data_url(region)},
                        }
                        for region in request.regions
                    ),
                ],
            }
        ]
        call_kwargs: dict[str, Any] = {
            "model": request.model_name,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.response_model_name,
                    "schema": request.response_schema,
                    "strict": True,
                },
            },
        }
        api_key_env_var = config.provider.api_key_env_var
        if api_key_env_var is not None:
            api_key = os.getenv(api_key_env_var)
            if api_key is not None:
                call_kwargs["api_key"] = api_key
        call_kwargs.update(config.provider.extra_body)

        try:
            response = self._default_completion_callable()(
                timeout=config.timeout_seconds,
                **call_kwargs,
            )
        except Exception as exc:  # pragma: no cover - exercised with mocked callables
            return ProviderInvocationResult(
                failure=_normalize_exception(
                    exc,
                    provider_name=self.provider_name,
                    model_name=request.model_name,
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
                )
            )

        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name=self.provider_name,
                model_name=request.model_name,
                assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                raw_response_payload=json_safe(payload),
                structured_output_json=structured_output,
                usage=_extract_usage(payload),
                status_code=200,
            )
        )


__all__ = ["LiteLLMMultimodalAdapter"]
