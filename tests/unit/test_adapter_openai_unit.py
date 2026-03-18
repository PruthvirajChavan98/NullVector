"""Unit tests for the OpenAI optional convenience adapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from nullvector.llm.adapters._openai import OpenAIAdapter, _classify_openai_error, _extract_usage
from nullvector.llm.types import (
    GatewayAssuranceMode,
    GatewayConfig,
    GatewayFailureCategory,
    GatewayUsage,
    LLMMessage,
    LLMRole,
    ProviderInvocationRequest,
    StructuredOutputMode,
)


def _make_exc(class_name: str, message: str, **attrs: Any) -> Exception:
    """Create an exception instance with a specific class name."""
    exc_cls = type(class_name, (Exception,), {})
    exc = exc_cls(message)
    for k, v in attrs.items():
        object.__setattr__(exc, k, v)
    return exc


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
    operation_name: str = "test-op",
) -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        request_id="req-1",
        operation_name=operation_name,
        messages=(LLMMessage(role=LLMRole.USER, content="hello"),),
        model_name="gpt-4.1-mini",
        structured_output_mode=mode,
        response_model_name="EchoResponse",
        response_schema_name="EchoResponse",
        response_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        timeout_seconds=30.0,
    )


def _mock_responses_response(output_text: str, *, response_id: str = "resp-1") -> MagicMock:
    """Build a mock OpenAI Responses API response object."""
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
    """Build a mock OpenAI Chat Completions API response object."""
    message = MagicMock()
    message.content = content
    message.refusal = None

    choice = MagicMock()
    choice.message = message

    usage = MagicMock(spec=[])
    usage.input_tokens = None  # Chat Completions uses prompt_tokens, not input_tokens
    usage.prompt_tokens = 8
    usage.output_tokens = None  # Chat Completions uses completion_tokens
    usage.completion_tokens = 4

    response = MagicMock()
    response.id = response_id
    response.choices = [choice]
    response.usage = usage
    response._request_id = "x-req-2"
    response.model_dump = MagicMock(return_value={"id": response_id, "content": content})
    return response


class TestOpenAIAdapterResponsesAPI:
    """Tests for Responses API (PROVIDER_NATIVE) path."""

    def test_success_returns_structured_json(self) -> None:
        payload = {"message": "hello from responses"}
        mock_response = _mock_responses_response(json.dumps(payload))

        client = MagicMock()
        client.responses.create.return_value = mock_response

        adapter = OpenAIAdapter(client=client)
        result = adapter.invoke(_make_request(), _make_config())

        assert result.success is not None
        assert result.failure is None
        assert result.success.structured_output_json == payload
        assert result.success.assurance_mode is GatewayAssuranceMode.PROVIDER_NATIVE_STRICT
        assert result.success.structured_output_mode is StructuredOutputMode.PROVIDER_NATIVE
        assert result.success.provider_response_id == "resp-1"
        assert result.success.usage is not None
        assert result.success.usage.input_tokens == 10
        assert result.success.usage.output_tokens == 5

    def test_refusal_returns_typed_failure(self) -> None:
        refusal_item = MagicMock()
        refusal_item.type = "refusal"
        refusal_item.refusal = "content policy violation"

        output_item = MagicMock()
        output_item.content = [refusal_item]

        response = MagicMock()
        response.id = "resp-refusal"
        response.output = [output_item]
        response.model_dump = MagicMock(return_value={"id": "resp-refusal"})

        client = MagicMock()
        client.responses.create.return_value = response

        adapter = OpenAIAdapter(client=client)
        result = adapter.invoke(_make_request(), _make_config())

        assert result.failure is not None
        assert result.failure.category is GatewayFailureCategory.PROVIDER_REFUSAL
        assert result.failure.retryable is False
        assert "content policy violation" in result.failure.message

    def test_exception_maps_to_failure(self) -> None:
        exc = _make_exc("APIConnectionError", "connection failed")

        client = MagicMock()
        client.responses.create.side_effect = exc

        adapter = OpenAIAdapter(client=client)
        result = adapter.invoke(_make_request(), _make_config())

        assert result.failure is not None
        assert result.failure.category is GatewayFailureCategory.NETWORK_FAILURE
        assert result.failure.retryable is True


class TestOpenAIAdapterChatCompletions:
    """Tests for Chat Completions API (TRANSPORT_COMPATIBLE) path."""

    def test_success_returns_structured_json(self) -> None:
        payload = {"message": "hello from chat"}
        mock_response = _mock_chat_response(json.dumps(payload))

        client = MagicMock()
        client.chat.completions.create.return_value = mock_response

        adapter = OpenAIAdapter(client=client)
        request = _make_request(mode=StructuredOutputMode.TRANSPORT_COMPATIBLE)
        result = adapter.invoke(request, _make_config())

        assert result.success is not None
        assert result.success.structured_output_json == payload
        assert result.success.assurance_mode is GatewayAssuranceMode.TRANSPORT_COMPATIBLE
        assert result.success.structured_output_mode is StructuredOutputMode.TRANSPORT_COMPATIBLE
        assert result.success.usage is not None
        assert result.success.usage.input_tokens == 8
        assert result.success.usage.output_tokens == 4

    def test_refusal_returns_typed_failure(self) -> None:
        message = MagicMock()
        message.content = None
        message.refusal = "I cannot help with that"

        choice = MagicMock()
        choice.message = message

        response = MagicMock()
        response.id = "chatcmpl-refusal"
        response.choices = [choice]
        response.model_dump = MagicMock(return_value={"id": "chatcmpl-refusal"})

        client = MagicMock()
        client.chat.completions.create.return_value = response

        adapter = OpenAIAdapter(client=client)
        request = _make_request(mode=StructuredOutputMode.TRANSPORT_COMPATIBLE)
        result = adapter.invoke(request, _make_config())

        assert result.failure is not None
        assert result.failure.category is GatewayFailureCategory.PROVIDER_REFUSAL

    def test_no_choices_returns_failure(self) -> None:
        response = MagicMock()
        response.choices = []
        response.model_dump = MagicMock(return_value={"choices": []})

        client = MagicMock()
        client.chat.completions.create.return_value = response

        adapter = OpenAIAdapter(client=client)
        request = _make_request(mode=StructuredOutputMode.TRANSPORT_COMPATIBLE)
        result = adapter.invoke(request, _make_config())

        assert result.failure is not None
        assert result.failure.category is GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE
        assert "no choices" in result.failure.message

    def test_exception_maps_to_failure(self) -> None:
        exc = _make_exc("RateLimitError", "rate limit exceeded")

        client = MagicMock()
        client.chat.completions.create.side_effect = exc

        adapter = OpenAIAdapter(client=client)
        request = _make_request(mode=StructuredOutputMode.TRANSPORT_COMPATIBLE)
        result = adapter.invoke(request, _make_config())

        assert result.failure is not None
        assert result.failure.category is GatewayFailureCategory.RATE_LIMIT
        assert result.failure.retryable is True


class TestOpenAIErrorClassification:
    """Tests for _classify_openai_error mapping."""

    @pytest.mark.parametrize(
        ("exc_class_name", "expected_category", "expected_retryable"),
        [
            ("APITimeoutError", GatewayFailureCategory.TIMEOUT, True),
            ("RateLimitError", GatewayFailureCategory.RATE_LIMIT, True),
            ("AuthenticationError", GatewayFailureCategory.AUTH_FAILURE, False),
            ("PermissionDeniedError", GatewayFailureCategory.AUTH_FAILURE, False),
            ("APIConnectionError", GatewayFailureCategory.NETWORK_FAILURE, True),
            ("NotFoundError", GatewayFailureCategory.UNSUPPORTED_CAPABILITY, False),
            ("InternalServerError", GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True),
            ("UnprocessableEntityError", GatewayFailureCategory.VALIDATION_FAILURE, False),
        ],
    )
    def test_exception_type_mapping(
        self,
        exc_class_name: str,
        expected_category: GatewayFailureCategory,
        expected_retryable: bool,
    ) -> None:
        exc = _make_exc(exc_class_name, "test")
        category, retryable = _classify_openai_error(exc)

        assert category is expected_category
        assert retryable is expected_retryable

    def test_bad_request_context_length(self) -> None:
        exc = _make_exc("BadRequestError", "maximum context_length exceeded")
        category, retryable = _classify_openai_error(exc)

        assert category is GatewayFailureCategory.CONTEXT_LENGTH_VIOLATION
        assert retryable is False

    def test_bad_request_generic(self) -> None:
        exc = _make_exc("BadRequestError", "invalid parameter")
        category, retryable = _classify_openai_error(exc)

        assert category is GatewayFailureCategory.VALIDATION_FAILURE
        assert retryable is False

    def test_unknown_exception_with_status_code(self) -> None:
        exc = _make_exc("SomeUnknownError", "server error", status_code=503)
        category, retryable = _classify_openai_error(exc)

        assert category is GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE
        assert retryable is True


class TestOpenAIUsageExtraction:
    """Tests for _extract_usage helper."""

    def test_responses_api_usage(self) -> None:
        usage = MagicMock()
        usage.input_tokens = 15
        usage.output_tokens = 7
        result = _extract_usage(usage)

        assert isinstance(result, GatewayUsage)
        assert result.input_tokens == 15
        assert result.output_tokens == 7

    def test_chat_completions_usage(self) -> None:
        usage = MagicMock(spec=[])
        usage.prompt_tokens = 12
        usage.completion_tokens = 6
        result = _extract_usage(usage)

        assert result.input_tokens == 12
        assert result.output_tokens == 6
