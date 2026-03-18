"""Optional OpenAI SDK adapter for the Phase 03 LLM gateway.

Requires the ``openai`` package (``pip install openai>=1.0.0``).
NullVector does **not** declare ``openai`` as a dependency — users install
it themselves and pass a configured ``openai.OpenAI`` client instance.
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


def _responses_api_messages(
    request: ProviderInvocationRequest,
) -> list[dict[str, Any]]:
    """Build OpenAI Responses API input messages from a provider request."""
    messages: list[dict[str, Any]] = []
    for msg in request.messages:
        if not request.attachments or msg != request.messages[-1]:
            messages.append({"role": msg.role.value, "content": msg.content})
        else:
            content: list[dict[str, Any]] = [{"type": "input_text", "text": msg.content}]
            for attachment in request.attachments:
                content.append(
                    {"type": "input_image", "image_url": _image_data_url(attachment)},
                )
            messages.append({"role": msg.role.value, "content": content})
    return messages


def _chat_api_messages(
    request: ProviderInvocationRequest,
) -> list[dict[str, Any]]:
    """Build OpenAI Chat Completions API messages from a provider request."""
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


def _classify_openai_error(exc: Exception) -> tuple[GatewayFailureCategory, bool]:
    """Map an OpenAI SDK exception to a failure category and retryable flag."""
    exc_type = type(exc).__name__
    exc_msg = str(exc).lower()

    category_map: dict[str, tuple[GatewayFailureCategory, bool]] = {
        "APITimeoutError": (GatewayFailureCategory.TIMEOUT, True),
        "RateLimitError": (GatewayFailureCategory.RATE_LIMIT, True),
        "AuthenticationError": (GatewayFailureCategory.AUTH_FAILURE, False),
        "PermissionDeniedError": (GatewayFailureCategory.AUTH_FAILURE, False),
        "APIConnectionError": (GatewayFailureCategory.NETWORK_FAILURE, True),
        "NotFoundError": (GatewayFailureCategory.UNSUPPORTED_CAPABILITY, False),
        "InternalServerError": (GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True),
        "UnprocessableEntityError": (GatewayFailureCategory.VALIDATION_FAILURE, False),
    }

    if exc_type in category_map:
        if exc_type == "BadRequestError" and "context_length" in exc_msg:
            return GatewayFailureCategory.CONTEXT_LENGTH_VIOLATION, False
        return category_map[exc_type]

    if exc_type == "BadRequestError":
        if "context_length" in exc_msg or "maximum context" in exc_msg:
            return GatewayFailureCategory.CONTEXT_LENGTH_VIOLATION, False
        return GatewayFailureCategory.VALIDATION_FAILURE, False

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        if status_code == 401 or status_code == 403:
            return GatewayFailureCategory.AUTH_FAILURE, False
        if status_code == 429:
            return GatewayFailureCategory.RATE_LIMIT, True
        if status_code >= 500:
            return GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True

    return GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True


def _build_failure(
    request: ProviderInvocationRequest,
    exc: Exception,
    *,
    structured_output_mode: StructuredOutputMode,
    assurance_mode: GatewayAssuranceMode,
) -> ProviderInvocationResult:
    """Build a typed failure result from an exception."""
    category, retryable = _classify_openai_error(exc)
    status_code = getattr(exc, "status_code", None)
    return ProviderInvocationResult(
        failure=ProviderInvocationFailure(
            provider_name="openai",
            model_name=request.model_name,
            assurance_mode=assurance_mode,
            structured_output_mode=structured_output_mode,
            category=category,
            message=str(exc),
            retryable=retryable,
            status_code=status_code if isinstance(status_code, int) else None,
        ),
    )


class OpenAIAdapter:
    """Optional convenience adapter wrapping an ``openai.OpenAI`` client.

    Supports both the Responses API (``PROVIDER_NATIVE`` mode) and
    Chat Completions API (``TRANSPORT_COMPATIBLE`` mode). The user
    creates and configures the ``OpenAI`` client themselves.

    Example::

        from openai import OpenAI
        from nullvector.llm import GatewayConfig, GatewayService
        from nullvector.llm.adapters import OpenAIAdapter

        client = OpenAI(api_key="sk-...")
        adapter = OpenAIAdapter(client=client)
        gateway = GatewayService(
            GatewayConfig(
                default_model="gpt-4.1-mini",
                supported_structured_output_modes=(
                    StructuredOutputMode.PROVIDER_NATIVE,
                    StructuredOutputMode.TRANSPORT_COMPATIBLE,
                ),
            ),
            provider_adapter=adapter,
        )
    """

    provider_name: str = "openai"

    def __init__(self, *, client: Any) -> None:
        self._client: Any = client

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        """Invoke the OpenAI API and return a normalized result."""
        del config
        if request.structured_output_mode == StructuredOutputMode.PROVIDER_NATIVE:
            return self._invoke_responses_api(request)
        return self._invoke_chat_completions(request)

    def _invoke_responses_api(
        self,
        request: ProviderInvocationRequest,
    ) -> ProviderInvocationResult:
        """Use the OpenAI Responses API for PROVIDER_NATIVE structured output."""
        assurance = GatewayAssuranceMode.PROVIDER_NATIVE_STRICT
        mode = StructuredOutputMode.PROVIDER_NATIVE
        try:
            kwargs: dict[str, Any] = {
                "model": request.model_name,
                "input": _responses_api_messages(request),
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
                kwargs["temperature"] = request.temperature
            if request.max_output_tokens is not None:
                kwargs["max_output_tokens"] = request.max_output_tokens
            if request.timeout_seconds:
                kwargs["timeout"] = request.timeout_seconds

            response = self._client.responses.create(**kwargs)
        except Exception as exc:
            return _build_failure(
                request,
                exc,
                structured_output_mode=mode,
                assurance_mode=assurance,
            )

        raw_payload = _safe_dump(response)
        output_items: list[Any] = getattr(response, "output", []) or []
        for item in output_items:
            content_list = getattr(item, "content", None) or []
            for content_item in content_list:
                item_type = getattr(content_item, "type", "")
                if item_type == "refusal":
                    refusal_text = getattr(content_item, "refusal", "provider refused request")
                    return ProviderInvocationResult(
                        failure=ProviderInvocationFailure(
                            provider_name="openai",
                            model_name=request.model_name,
                            assurance_mode=assurance,
                            structured_output_mode=mode,
                            category=GatewayFailureCategory.PROVIDER_REFUSAL,
                            message=refusal_text,
                            retryable=False,
                            raw_response_payload=raw_payload,
                            provider_response_id=getattr(response, "id", None),
                        ),
                    )

        output_text = getattr(response, "output_text", None)
        usage = getattr(response, "usage", None)
        gateway_usage = _extract_usage(usage) if usage is not None else None
        request_id_header = getattr(response, "_request_id", None)
        response_id = getattr(response, "id", None)

        structured_json: JSONValue | None = None
        structured_text = output_text
        if output_text:
            try:
                structured_json = json.loads(output_text)
                structured_text = None
            except (json.JSONDecodeError, TypeError):
                pass

        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name="openai",
                model_name=request.model_name,
                assurance_mode=assurance,
                structured_output_mode=mode,
                raw_request_payload=_safe_request_dump(request),
                raw_response_payload=raw_payload,
                structured_output_json=structured_json,
                structured_output_text=structured_text,
                usage=gateway_usage,
                status_code=200,
                provider_request_id=request_id_header,
                provider_response_id=response_id,
            ),
        )

    def _invoke_chat_completions(
        self,
        request: ProviderInvocationRequest,
    ) -> ProviderInvocationResult:
        """Use the Chat Completions API for TRANSPORT_COMPATIBLE structured output."""
        assurance = GatewayAssuranceMode.TRANSPORT_COMPATIBLE
        mode = StructuredOutputMode.TRANSPORT_COMPATIBLE
        try:
            kwargs: dict[str, Any] = {
                "model": request.model_name,
                "messages": _chat_api_messages(request),
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
                kwargs["temperature"] = request.temperature
            if request.max_output_tokens is not None:
                kwargs["max_tokens"] = request.max_output_tokens
            if request.timeout_seconds:
                kwargs["timeout"] = request.timeout_seconds

            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            return _build_failure(
                request,
                exc,
                structured_output_mode=mode,
                assurance_mode=assurance,
            )

        raw_payload = _safe_dump(response)
        choices = getattr(response, "choices", []) or []
        if not choices:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name="openai",
                    model_name=request.model_name,
                    assurance_mode=assurance,
                    structured_output_mode=mode,
                    category=GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE,
                    message="response contained no choices",
                    retryable=False,
                    raw_response_payload=raw_payload,
                ),
            )

        choice = choices[0]
        message = getattr(choice, "message", None)
        refusal = getattr(message, "refusal", None) if message else None
        if refusal:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name="openai",
                    model_name=request.model_name,
                    assurance_mode=assurance,
                    structured_output_mode=mode,
                    category=GatewayFailureCategory.PROVIDER_REFUSAL,
                    message=refusal,
                    retryable=False,
                    raw_response_payload=raw_payload,
                    provider_response_id=getattr(response, "id", None),
                ),
            )

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
                provider_name="openai",
                model_name=request.model_name,
                assurance_mode=assurance,
                structured_output_mode=mode,
                raw_request_payload=_safe_request_dump(request),
                raw_response_payload=raw_payload,
                structured_output_json=structured_json,
                structured_output_text=structured_text,
                usage=gateway_usage,
                status_code=200,
                provider_request_id=getattr(response, "_request_id", None),
                provider_response_id=getattr(response, "id", None),
            ),
        )


def _extract_usage(usage: Any) -> GatewayUsage:
    """Extract token usage from an OpenAI response usage object."""
    input_tokens = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None) or getattr(
        usage, "completion_tokens", None
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


__all__ = ["OpenAIAdapter"]
