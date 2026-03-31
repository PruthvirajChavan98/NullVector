"""Unit tests for the async OpenAI optional convenience adapter."""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from nullvector.llm.adapters._openai import AsyncOpenAIAdapter
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
    return GatewayConfig(
        default_model="gpt-4.1-mini",
        supported_structured_output_modes=(
            StructuredOutputMode.PROVIDER_NATIVE,
            StructuredOutputMode.TRANSPORT_COMPATIBLE,
        ),
    )


def _make_request(
    *,
    mode: StructuredOutputMode = StructuredOutputMode.PROVIDER_NATIVE,
) -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        request_id="req-1",
        operation_name="test-op",
        messages=(LLMMessage(role=LLMRole.USER, content="hello"),),
        model_name="gpt-4.1-mini",
        structured_output_mode=mode,
        response_model_name="EchoResponse",
        response_schema_name="EchoResponse",
        response_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        timeout_seconds=30.0,
    )


def _mock_responses_response(output_text: str, *, response_id: str = "resp-1") -> MagicMock:
    content_item = MagicMock()
    content_item.type = "output_text"
    content_item.text = output_text

    output_item = MagicMock()
    output_item.content = [content_item]

    usage = MagicMock()
    usage.input_tokens = 10
    usage.output_tokens = 5

    response = MagicMock()
    response.id = response_id
    response.output = [output_item]
    response.output_text = output_text
    response.usage = usage
    response._request_id = "x-req-1"
    response.model_dump = MagicMock(return_value={"id": response_id, "output_text": output_text})
    return response


def _mock_chat_response(content: str, *, response_id: str = "chatcmpl-1") -> MagicMock:
    message = MagicMock()
    message.content = content
    message.refusal = None

    choice = MagicMock()
    choice.message = message

    usage = MagicMock(spec=[])
    usage.input_tokens = None
    usage.prompt_tokens = 8
    usage.output_tokens = None
    usage.completion_tokens = 4

    response = MagicMock()
    response.id = response_id
    response.choices = [choice]
    response.usage = usage
    response._request_id = "x-req-2"
    response.model_dump = MagicMock(return_value={"id": response_id, "content": content})
    return response


async def test_async_openai_adapter_provider_native_success() -> None:
    payload = {"message": "hello from responses"}
    mock_response = _mock_responses_response(json.dumps(payload))

    client = MagicMock()
    client.responses.create = AsyncMock(return_value=mock_response)

    adapter = AsyncOpenAIAdapter(client=client)
    result = await adapter.invoke(_make_request(), _make_config())

    assert result.success is not None
    assert result.failure is None
    assert result.success.structured_output_json == payload
    assert result.success.assurance_mode is GatewayAssuranceMode.PROVIDER_NATIVE_STRICT


async def test_async_openai_adapter_transport_success() -> None:
    payload = {"message": "hello from chat"}
    mock_response = _mock_chat_response(json.dumps(payload))

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=mock_response)

    adapter = AsyncOpenAIAdapter(client=client)
    result = await adapter.invoke(
        _make_request(mode=StructuredOutputMode.TRANSPORT_COMPATIBLE),
        _make_config(),
    )

    assert result.success is not None
    assert result.success.structured_output_json == payload
    assert result.success.assurance_mode is GatewayAssuranceMode.TRANSPORT_COMPATIBLE


async def test_async_openai_adapter_exception_maps_to_failure() -> None:
    exc = _make_exc("RateLimitError", "rate limit exceeded")

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=exc)

    adapter = AsyncOpenAIAdapter(client=client)
    result = await adapter.invoke(
        _make_request(mode=StructuredOutputMode.TRANSPORT_COMPATIBLE),
        _make_config(),
    )

    assert result.failure is not None
    assert result.failure.category is GatewayFailureCategory.RATE_LIMIT
    assert result.failure.retryable is True
