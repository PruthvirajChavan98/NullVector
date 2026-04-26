"""Optional LiteLLM adapter for the Phase 03 LLM gateway.

Requires the ``litellm`` package (``pip install litellm>=1.79.0``).
NullVector does **not** declare ``litellm`` as a dependency — users install
it themselves and optionally pass a custom ``completion`` callable.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

from nullvector.llm.types import (
    GatewayAssuranceMode,
    GatewayConfig,
    GatewayFailureCategory,
    GatewayUsage,
    JSONValue,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    RegionImageInput,
    StructuredOutputMode,
)


def _image_data_url(region: RegionImageInput) -> str:
    """Encode an image attachment as a base64 data URI."""
    raw = Path(region.image_path).read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    media_type = region.media_type or mimetypes.guess_type(region.image_path)[0] or "image/png"
    return f"data:{media_type};base64,{encoded}"


def _build_messages(
    request: ProviderInvocationRequest,
) -> list[dict[str, Any]]:
    """Build Chat Completions API messages from a provider request."""
    messages: list[dict[str, Any]] = []
    for msg in request.messages:
        if not request.attachments or msg != request.messages[-1]:
            messages.append({"role": msg.role.value, "content": msg.content})
        else:
            content: list[dict[str, Any]] = [{"type": "text", "text": msg.content}]
            for attachment in request.attachments:
                content.append(
                    {"type": "image_url", "image_url": {"url": _image_data_url(attachment)}},
                )
            messages.append({"role": msg.role.value, "content": content})
    return messages


def _classify_litellm_error(exc: Exception) -> tuple[GatewayFailureCategory, bool]:
    """Map a LiteLLM exception to a failure category and retryable flag."""
    exc_type = type(exc).__name__

    category_map: dict[str, tuple[GatewayFailureCategory, bool]] = {
        "Timeout": (GatewayFailureCategory.TIMEOUT, True),
        "RateLimitError": (GatewayFailureCategory.RATE_LIMIT, True),
        "AuthenticationError": (GatewayFailureCategory.AUTH_FAILURE, False),
        "ContextWindowExceededError": (GatewayFailureCategory.CONTEXT_LENGTH_VIOLATION, False),
        "ContentPolicyViolationError": (GatewayFailureCategory.PROVIDER_REFUSAL, False),
        "APIConnectionError": (GatewayFailureCategory.NETWORK_FAILURE, True),
        "NotFoundError": (GatewayFailureCategory.UNSUPPORTED_CAPABILITY, False),
        "InternalServerError": (GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True),
        "ServiceUnavailableError": (GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True),
        "UnprocessableEntityError": (GatewayFailureCategory.VALIDATION_FAILURE, False),
        "BadRequestError": (GatewayFailureCategory.VALIDATION_FAILURE, False),
        "PermissionDeniedError": (GatewayFailureCategory.AUTH_FAILURE, False),
    }

    if exc_type in category_map:
        return category_map[exc_type]

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        if status_code in (401, 403):
            return GatewayFailureCategory.AUTH_FAILURE, False
        if status_code == 429:
            return GatewayFailureCategory.RATE_LIMIT, True
        if status_code >= 500:
            return GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True

    return GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True


def _build_failure(
    request: ProviderInvocationRequest,
    exc: Exception,
) -> ProviderInvocationResult:
    """Build a typed failure result from an exception."""
    category, retryable = _classify_litellm_error(exc)
    status_code = getattr(exc, "status_code", None)
    return ProviderInvocationResult(
        failure=ProviderInvocationFailure(
            provider_name="litellm",
            model_name=request.model_name,
            assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
            structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
            category=category,
            message=str(exc),
            retryable=retryable,
            status_code=status_code if isinstance(status_code, int) else None,
        ),
    )


def _get_default_completion() -> Any:
    """Lazily import and return litellm.completion at runtime."""
    try:
        import litellm
    except ImportError:
        msg = (
            "litellm is required for LiteLLMAdapter but is not installed. "
            "Install it with: pip install litellm>=1.79.0"
        )
        raise ImportError(msg) from None
    return litellm.completion


def _get_default_acompletion() -> Any:
    """Lazily import and return litellm.acompletion at runtime."""
    try:
        import litellm
    except ImportError:
        msg = (
            "litellm is required for AsyncLiteLLMAdapter but is not installed. "
            "Install it with: pip install litellm>=1.79.0"
        )
        raise ImportError(msg) from None
    return litellm.acompletion


class LiteLLMAdapter:
    """Optional convenience adapter wrapping the ``litellm.completion`` callable.

    Only supports ``TRANSPORT_COMPATIBLE`` structured output mode via the
    Chat Completions ``response_format`` parameter. Returns an
    ``UNSUPPORTED_CAPABILITY`` failure for ``PROVIDER_NATIVE`` mode.

    Example::

        from nullvector.llm import GatewayConfig, GatewayService
        from nullvector.llm.adapters import LiteLLMAdapter

        adapter = LiteLLMAdapter(api_key="sk-or-...")
        gateway = GatewayService(
            GatewayConfig(default_model="openrouter/google/gemini-2.5-flash"),
            provider_adapter=adapter,
        )

    Any extra keyword arguments are forwarded to every ``litellm.completion``
    call (e.g. ``api_base``, ``api_version``, ``custom_llm_provider``)::

        adapter = LiteLLMAdapter(api_key="sk-...", api_base="https://my-proxy")

    For testing without the ``litellm`` package installed, inject a mock
    callable via ``completion_fn``::

        adapter = LiteLLMAdapter(completion_fn=my_mock_completion)
    """

    provider_name: str = "litellm"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        completion_fn: Any | None = None,
        **completion_kwargs: Any,
    ) -> None:
        self._completion_fn: Any | None = completion_fn
        self._extra_kwargs: dict[str, Any] = completion_kwargs
        if api_key is not None:
            self._extra_kwargs["api_key"] = api_key

    def _get_completion_fn(self) -> Any:
        """Return the completion callable, lazily importing litellm if needed."""
        if self._completion_fn is not None:
            return self._completion_fn
        self._completion_fn = _get_default_completion()
        return self._completion_fn

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        """Invoke the LiteLLM completion API and return a normalized result."""
        del config
        if request.structured_output_mode == StructuredOutputMode.PROVIDER_NATIVE:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name="litellm",
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=StructuredOutputMode.PROVIDER_NATIVE,
                    category=GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
                    message=(
                        "LiteLLMAdapter only supports TRANSPORT_COMPATIBLE mode. "
                        "Use OpenAIAdapter for PROVIDER_NATIVE structured output."
                    ),
                    retryable=False,
                ),
            )

        try:
            completion_fn = self._get_completion_fn()
            kwargs: dict[str, Any] = {
                "model": request.model_name,
                "messages": _build_messages(request),
            }
            if request.response_schema is not None:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.response_schema_name,
                        "schema": request.response_schema,
                        "strict": True,
                    },
                }
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.max_output_tokens is not None:
                kwargs["max_tokens"] = request.max_output_tokens
            if request.timeout_seconds:
                kwargs["timeout"] = request.timeout_seconds
            kwargs.update(self._extra_kwargs)

            response = completion_fn(**kwargs)
        except ImportError:
            raise
        except Exception as exc:
            return _build_failure(request, exc)

        raw_payload = _safe_dump(response)
        choices = getattr(response, "choices", []) or []
        if not choices:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name="litellm",
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                    category=GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE,
                    message="response contained no choices",
                    retryable=False,
                    raw_response_payload=raw_payload,
                ),
            )

        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message else None
        usage = getattr(response, "usage", None)
        gateway_usage = _extract_usage(usage) if usage is not None else None

        structured_json: JSONValue | None = None
        structured_text = content
        if content:
            try:
                structured_json = json.loads(content)
                structured_text = None
            except (json.JSONDecodeError, TypeError):
                pass

        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name="litellm",
                model_name=request.model_name,
                assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                raw_request_payload=_safe_request_dump(request),
                raw_response_payload=raw_payload,
                structured_output_json=structured_json,
                structured_output_text=structured_text,
                usage=gateway_usage,
                status_code=200,
                provider_request_id=getattr(response, "_hidden_params", {}).get("unique_id", None),
                provider_response_id=getattr(response, "id", None),
            ),
        )


def _extract_usage(usage: Any) -> GatewayUsage:
    """Extract token usage from a LiteLLM response usage object."""
    input_tokens = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "completion_tokens", None) or getattr(
        usage, "output_tokens", None
    )
    return GatewayUsage(
        input_tokens=input_tokens or 0,
        output_tokens=output_tokens or 0,
    )


def _safe_dump(obj: Any) -> JSONValue | None:
    """Attempt to serialize an SDK response for audit."""
    try:
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")  # type: ignore[no-any-return]
        return json.loads(json.dumps(vars(obj), default=str))  # type: ignore[no-any-return]
    except Exception:
        return None


def _safe_request_dump(request: ProviderInvocationRequest) -> JSONValue:
    """Serialize the provider request for audit."""
    return request.model_dump(mode="json")


class AsyncLiteLLMAdapter:
    """Async convenience adapter wrapping ``litellm.acompletion``."""

    provider_name: str = "litellm"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        acompletion_fn: Any | None = None,
        **completion_kwargs: Any,
    ) -> None:
        self._acompletion_fn: Any | None = acompletion_fn
        self._extra_kwargs: dict[str, Any] = completion_kwargs
        if api_key is not None:
            self._extra_kwargs["api_key"] = api_key

    def _get_acompletion_fn(self) -> Any:
        if self._acompletion_fn is not None:
            return self._acompletion_fn
        self._acompletion_fn = _get_default_acompletion()
        return self._acompletion_fn

    async def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        """Invoke the LiteLLM completion API asynchronously."""
        del config
        if request.structured_output_mode == StructuredOutputMode.PROVIDER_NATIVE:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name="litellm",
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=StructuredOutputMode.PROVIDER_NATIVE,
                    category=GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
                    message=(
                        "AsyncLiteLLMAdapter only supports TRANSPORT_COMPATIBLE mode. "
                        "Use AsyncOpenAIAdapter for PROVIDER_NATIVE structured output."
                    ),
                    retryable=False,
                ),
            )

        try:
            acompletion_fn = self._get_acompletion_fn()
            kwargs: dict[str, Any] = {
                "model": request.model_name,
                "messages": _build_messages(request),
            }
            if request.response_schema is not None:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.response_schema_name,
                        "schema": request.response_schema,
                        "strict": True,
                    },
                }
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.max_output_tokens is not None:
                kwargs["max_tokens"] = request.max_output_tokens
            if request.timeout_seconds:
                kwargs["timeout"] = request.timeout_seconds
            kwargs.update(self._extra_kwargs)

            response = await acompletion_fn(**kwargs)
        except ImportError:
            raise
        except Exception as exc:
            return _build_failure(request, exc)

        raw_payload = _safe_dump(response)
        choices = getattr(response, "choices", []) or []
        if not choices:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name="litellm",
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                    category=GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE,
                    message="response contained no choices",
                    retryable=False,
                    raw_response_payload=raw_payload,
                ),
            )

        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message else None
        usage = getattr(response, "usage", None)
        gateway_usage = _extract_usage(usage) if usage is not None else None

        structured_json: JSONValue | None = None
        structured_text = content
        if content:
            try:
                structured_json = json.loads(content)
                structured_text = None
            except (json.JSONDecodeError, TypeError):
                pass

        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name="litellm",
                model_name=request.model_name,
                assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                raw_request_payload=_safe_request_dump(request),
                raw_response_payload=raw_payload,
                structured_output_json=structured_json,
                structured_output_text=structured_text,
                usage=gateway_usage,
                status_code=200,
                provider_request_id=getattr(response, "_hidden_params", {}).get("unique_id", None),
                provider_response_id=getattr(response, "id", None),
            ),
        )


__all__ = ["AsyncLiteLLMAdapter", "LiteLLMAdapter"]
