"""Direct OpenAI Responses API adapter with provider-native strict assurance."""

from __future__ import annotations

import os
from typing import Any, cast

import httpx

from strataforge.llm.audit import json_safe
from strataforge.llm.types import (
    GatewayAssuranceMode,
    GatewayConfig,
    GatewayFailureCategory,
    GatewayUsage,
    JSONValue,
    OpenAIProviderConfig,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    StructuredOutputMode,
)


def _extract_json_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"text": response.text}
    if isinstance(payload, dict):
        return cast(dict[str, Any], payload)
    return {"payload": payload}


def _extract_output_text(payload: dict[str, Any]) -> str | None:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    for item in cast(list[Any], payload.get("output", [])):
        if not isinstance(item, dict):
            continue
        for content in cast(list[Any], item.get("content", [])):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return None


def _extract_output_json(payload: dict[str, Any]) -> JSONValue | None:
    for item in cast(list[Any], payload.get("output", [])):
        if not isinstance(item, dict):
            continue
        for content in cast(list[Any], item.get("content", [])):
            if not isinstance(content, dict):
                continue
            if "parsed" in content:
                return json_safe(content["parsed"])
    return None


def _extract_refusal(payload: dict[str, Any]) -> str | None:
    for item in cast(list[Any], payload.get("output", [])):
        if not isinstance(item, dict):
            continue
        for content in cast(list[Any], item.get("content", [])):
            if not isinstance(content, dict):
                continue
            refusal = content.get("refusal")
            if isinstance(refusal, str) and refusal.strip():
                return refusal
            if content.get("type") == "refusal" and isinstance(content.get("text"), str):
                return cast(str, content["text"])
    return None


def _extract_usage(payload: dict[str, Any]) -> GatewayUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens") or 0
    output_tokens = usage.get("output_tokens") or 0
    total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)
    if not all(isinstance(value, int) for value in (input_tokens, output_tokens, total_tokens)):
        return None
    return GatewayUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _failure_from_response(
    *,
    request: ProviderInvocationRequest,
    model_name: str,
    payload: dict[str, Any],
    status_code: int,
    provider_request_id: str | None,
    provider_response_id: str | None,
    raw_request_payload: dict[str, Any],
) -> ProviderInvocationFailure:
    message = (
        cast(dict[str, Any], payload.get("error", {})).get("message")
        if isinstance(payload.get("error"), dict)
        else None
    )
    message_value = (
        str(message) if message is not None else f"OpenAI request failed with {status_code}"
    )
    message_key = message_value.casefold()

    category = GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE
    retryable = True
    if status_code == 429:
        category = GatewayFailureCategory.RATE_LIMIT
    elif status_code in (401, 403):
        category = GatewayFailureCategory.AUTH_FAILURE
        retryable = False
    elif status_code in (408, 504):
        category = GatewayFailureCategory.TIMEOUT
    elif "context" in message_key and "length" in message_key:
        category = GatewayFailureCategory.CONTEXT_LENGTH_VIOLATION
        retryable = False
    elif "refusal" in message_key or "content filter" in message_key:
        category = GatewayFailureCategory.PROVIDER_REFUSAL
        retryable = False
    elif "unsupported" in message_key or "not supported" in message_key:
        category = GatewayFailureCategory.UNSUPPORTED_CAPABILITY
        retryable = False
    elif status_code >= 400:
        category = GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE

    return ProviderInvocationFailure(
        provider_name="openai_http",
        model_name=model_name,
        assurance_mode=GatewayAssuranceMode.PROVIDER_NATIVE_STRICT,
        structured_output_mode=request.structured_output_mode,
        category=category,
        message=message_value,
        retryable=retryable,
        raw_request_payload=json_safe(raw_request_payload),
        raw_response_payload=json_safe(payload),
        status_code=status_code,
        provider_request_id=provider_request_id,
        provider_response_id=provider_response_id,
        provider_error_code=(
            str(cast(dict[str, Any], payload.get("error", {})).get("code"))
            if isinstance(payload.get("error"), dict)
            and cast(dict[str, Any], payload.get("error", {})).get("code") is not None
            else None
        ),
    )


class OpenAIResponsesHTTPAdapter:
    """Direct provider-native strict adapter for the OpenAI Responses API."""

    provider_name = "openai_http"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client()
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        provider = config.provider
        if not isinstance(provider, OpenAIProviderConfig):
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.PROVIDER_NATIVE_STRICT,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="OpenAI adapter requires OpenAIProviderConfig",
                    retryable=False,
                    raw_request_payload=request.model_dump(mode="json"),
                ),
            )
        if request.structured_output_mode != StructuredOutputMode.PROVIDER_NATIVE:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.PROVIDER_NATIVE_STRICT,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="OpenAI strict adapter requires provider-native structured output mode",
                    retryable=False,
                    raw_request_payload=request.model_dump(mode="json"),
                ),
            )

        api_key = os.getenv(provider.api_key_env_var)
        if api_key is None:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.PROVIDER_NATIVE_STRICT,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.AUTH_FAILURE,
                    message="configured OpenAI API key environment variable is not set",
                    retryable=False,
                    raw_request_payload=request.model_dump(mode="json"),
                    details={"api_key_env_var": provider.api_key_env_var},
                ),
            )

        raw_request_payload: dict[str, Any] = {
            "model": request.model_name,
            "input": [
                {
                    "role": message.role.value,
                    "content": message.content,
                }
                for message in request.messages
            ],
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
        raw_request_payload.update(provider.extra_body)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider.organization_env_var is not None:
            organization = os.getenv(provider.organization_env_var)
            if organization is not None:
                headers["OpenAI-Organization"] = organization
        if provider.project_env_var is not None:
            project = os.getenv(provider.project_env_var)
            if project is not None:
                headers["OpenAI-Project"] = project
        if request.idempotency_key is not None:
            headers["Idempotency-Key"] = request.idempotency_key

        try:
            response = self._client.post(
                f"{provider.base_url.rstrip('/')}/responses",
                json=raw_request_payload,
                headers=headers,
                timeout=config.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.PROVIDER_NATIVE_STRICT,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.TIMEOUT,
                    message=str(exc) or "OpenAI request timed out",
                    retryable=True,
                    raw_request_payload=json_safe(raw_request_payload),
                ),
            )
        except httpx.TransportError as exc:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.PROVIDER_NATIVE_STRICT,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.NETWORK_FAILURE,
                    message=str(exc) or "OpenAI transport error",
                    retryable=True,
                    raw_request_payload=json_safe(raw_request_payload),
                ),
            )

        payload = _extract_json_payload(response)
        provider_request_id = response.headers.get("x-request-id")
        provider_response_id = str(payload.get("id")) if payload.get("id") is not None else None
        if response.status_code >= 400:
            return ProviderInvocationResult(
                failure=_failure_from_response(
                    request=request,
                    model_name=request.model_name,
                    payload=payload,
                    status_code=response.status_code,
                    provider_request_id=provider_request_id,
                    provider_response_id=provider_response_id,
                    raw_request_payload=raw_request_payload,
                ),
            )

        refusal_message = _extract_refusal(payload)
        if refusal_message is not None:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.PROVIDER_NATIVE_STRICT,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.PROVIDER_REFUSAL,
                    message=refusal_message,
                    retryable=False,
                    raw_request_payload=json_safe(raw_request_payload),
                    raw_response_payload=json_safe(payload),
                    status_code=response.status_code,
                    provider_request_id=provider_request_id,
                    provider_response_id=provider_response_id,
                ),
            )

        usage = _extract_usage(payload)
        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name=self.provider_name,
                model_name=request.model_name,
                assurance_mode=GatewayAssuranceMode.PROVIDER_NATIVE_STRICT,
                structured_output_mode=StructuredOutputMode.PROVIDER_NATIVE,
                raw_request_payload=json_safe(raw_request_payload),
                raw_response_payload=json_safe(payload),
                structured_output_json=_extract_output_json(payload),
                structured_output_text=_extract_output_text(payload),
                usage=usage,
                status_code=response.status_code,
                provider_request_id=provider_request_id,
                provider_response_id=provider_response_id,
            ),
        )
