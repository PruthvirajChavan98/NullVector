"""Unit tests for the async LiteLLM optional convenience adapter."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from nullvector.llm.adapters._litellm import AsyncLiteLLMAdapter
from nullvector.llm.types import (
    GatewayAssuranceMode,
    GatewayConfig,
    GatewayFailureCategory,
    LLMMessage,
    LLMRole,
    ProviderInvocationRequest,
    StructuredOutputMode,
)


def _make_exc(class_name: str, message: str, **attrs: Any) -> Exception:
    exc_cls = type(class_name, (Exception,), {})
    exc = exc_cls(message)
    for key, value in attrs.items():
        object.__setattr__(exc, key, value)
    return cast(Exception, exc)


def _make_config() -> GatewayConfig:
    return GatewayConfig(default_model="openai/gpt-4.1-mini")


def _make_request(
    *,
    mode: StructuredOutputMode = StructuredOutputMode.TRANSPORT_COMPATIBLE,
) -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        request_id="req-1",
        operation_name="test-op",
        messages=(LLMMessage(role=LLMRole.USER, content="hello"),),
        model_name="openai/gpt-4.1-mini",
        structured_output_mode=mode,
        response_model_name="EchoResponse",
        response_schema_name="EchoResponse",
        response_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        timeout_seconds=30.0,
    )


def _mock_completion_response(content: str, *, response_id: str = "chatcmpl-lit-1") -> MagicMock:
    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5

    response = MagicMock()
    response.id = response_id
    response.choices = [choice]
    response.usage = usage
    response._hidden_params = {"unique_id": "x-lit-req-1"}
    response.model_dump = MagicMock(return_value={"id": response_id, "content": content})
    return response


async def _return_response(response: MagicMock) -> MagicMock:
    return response


async def test_async_litellm_adapter_transport_success() -> None:
    payload = {"message": "hello from litellm"}
    mock_response = _mock_completion_response(json.dumps(payload))

    adapter = AsyncLiteLLMAdapter(acompletion_fn=lambda **_: _return_response(mock_response))
    result = await adapter.invoke(_make_request(), _make_config())

    assert result.success is not None
    assert result.failure is None
    assert result.success.structured_output_json == payload
    assert result.success.assurance_mode is GatewayAssuranceMode.TRANSPORT_COMPATIBLE


async def test_async_litellm_adapter_provider_native_returns_unsupported() -> None:
    adapter = AsyncLiteLLMAdapter(acompletion_fn=lambda **_: _return_response(MagicMock()))
    result = await adapter.invoke(
        _make_request(mode=StructuredOutputMode.PROVIDER_NATIVE),
        _make_config(),
    )

    assert result.failure is not None
    assert result.failure.category is GatewayFailureCategory.UNSUPPORTED_CAPABILITY
    assert result.failure.retryable is False


async def test_async_litellm_adapter_exception_maps_to_failure() -> None:
    async def _raise_error(**_: Any) -> MagicMock:
        raise _make_exc("RateLimitError", "rate limit exceeded")

    adapter = AsyncLiteLLMAdapter(acompletion_fn=_raise_error)
    result = await adapter.invoke(_make_request(), _make_config())

    assert result.failure is not None
    assert result.failure.category is GatewayFailureCategory.RATE_LIMIT
    assert result.failure.retryable is True


async def test_async_litellm_adapter_import_error_propagates() -> None:
    try:
        import litellm  # noqa: F401

        pytest.skip("litellm is installed; ImportError path cannot be tested")
    except ImportError:
        pass

    adapter = AsyncLiteLLMAdapter()
    with pytest.raises(ImportError, match="AsyncLiteLLMAdapter"):
        await adapter.invoke(_make_request(), _make_config())
