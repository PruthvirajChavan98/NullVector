"""Unit tests for the LiteLLM optional convenience adapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from nullvector.llm.adapters._litellm import (
    LiteLLMAdapter,
    _classify_litellm_error,
    _extract_usage,
)
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
    return GatewayConfig(default_model="openai/gpt-4.1-mini")


def _make_request(
    *,
    mode: StructuredOutputMode = StructuredOutputMode.TRANSPORT_COMPATIBLE,
    operation_name: str = "test-op",
) -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        request_id="req-1",
        operation_name=operation_name,
        messages=(LLMMessage(role=LLMRole.USER, content="hello"),),
        model_name="openai/gpt-4.1-mini",
        structured_output_mode=mode,
        response_model_name="EchoResponse",
        response_schema_name="EchoResponse",
        response_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        timeout_seconds=30.0,
    )


def _mock_completion_response(content: str, *, response_id: str = "chatcmpl-lit-1") -> MagicMock:
    """Build a mock LiteLLM ModelResponse."""
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


class TestLiteLLMAdapterSuccess:
    """Tests for the LiteLLM adapter success path."""

    def test_transport_compatible_success(self) -> None:
        payload = {"message": "hello from litellm"}
        mock_response = _mock_completion_response(json.dumps(payload))
        mock_fn = MagicMock(return_value=mock_response)

        adapter = LiteLLMAdapter(completion_fn=mock_fn)
        result = adapter.invoke(_make_request(), _make_config())

        assert result.success is not None
        assert result.failure is None
        assert result.success.structured_output_json == payload
        assert result.success.assurance_mode is GatewayAssuranceMode.TRANSPORT_COMPATIBLE
        assert result.success.structured_output_mode is StructuredOutputMode.TRANSPORT_COMPATIBLE
        assert result.success.provider_response_id == "chatcmpl-lit-1"
        assert result.success.usage is not None
        assert result.success.usage.input_tokens == 10
        assert result.success.usage.output_tokens == 5

        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-4.1-mini"
        assert call_kwargs["response_format"]["type"] == "json_schema"
        assert call_kwargs["response_format"]["json_schema"]["strict"] is True

    def test_unparseable_content_returns_text(self) -> None:
        mock_response = _mock_completion_response("not valid json")
        mock_fn = MagicMock(return_value=mock_response)

        adapter = LiteLLMAdapter(completion_fn=mock_fn)
        result = adapter.invoke(_make_request(), _make_config())

        assert result.success is not None
        assert result.success.structured_output_json is None
        assert result.success.structured_output_text == "not valid json"


class TestLiteLLMAdapterFailures:
    """Tests for the LiteLLM adapter failure paths."""

    def test_provider_native_returns_unsupported(self) -> None:
        mock_fn = MagicMock()
        adapter = LiteLLMAdapter(completion_fn=mock_fn)
        request = _make_request(mode=StructuredOutputMode.PROVIDER_NATIVE)
        result = adapter.invoke(request, _make_config())

        assert result.failure is not None
        assert result.failure.category is GatewayFailureCategory.UNSUPPORTED_CAPABILITY
        assert result.failure.retryable is False
        assert "TRANSPORT_COMPATIBLE" in result.failure.message
        mock_fn.assert_not_called()

    def test_no_choices_returns_failure(self) -> None:
        response = MagicMock()
        response.choices = []
        response.model_dump = MagicMock(return_value={"choices": []})

        mock_fn = MagicMock(return_value=response)
        adapter = LiteLLMAdapter(completion_fn=mock_fn)
        result = adapter.invoke(_make_request(), _make_config())

        assert result.failure is not None
        assert result.failure.category is GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE
        assert "no choices" in result.failure.message

    def test_exception_maps_to_failure(self) -> None:
        exc = _make_exc("RateLimitError", "rate limit exceeded")

        mock_fn = MagicMock(side_effect=exc)
        adapter = LiteLLMAdapter(completion_fn=mock_fn)
        result = adapter.invoke(_make_request(), _make_config())

        assert result.failure is not None
        assert result.failure.category is GatewayFailureCategory.RATE_LIMIT
        assert result.failure.retryable is True

    def test_import_error_propagates(self) -> None:
        try:
            import litellm  # noqa: F401

            pytest.skip("litellm is installed; ImportError path cannot be tested")
        except ImportError:
            pass
        adapter = LiteLLMAdapter()
        with pytest.raises(ImportError, match="litellm is required"):
            adapter.invoke(_make_request(), _make_config())


class TestLiteLLMErrorClassification:
    """Tests for _classify_litellm_error mapping."""

    @pytest.mark.parametrize(
        ("exc_class_name", "expected_category", "expected_retryable"),
        [
            ("Timeout", GatewayFailureCategory.TIMEOUT, True),
            ("RateLimitError", GatewayFailureCategory.RATE_LIMIT, True),
            ("AuthenticationError", GatewayFailureCategory.AUTH_FAILURE, False),
            ("ContextWindowExceededError", GatewayFailureCategory.CONTEXT_LENGTH_VIOLATION, False),
            ("ContentPolicyViolationError", GatewayFailureCategory.PROVIDER_REFUSAL, False),
            ("APIConnectionError", GatewayFailureCategory.NETWORK_FAILURE, True),
            ("NotFoundError", GatewayFailureCategory.UNSUPPORTED_CAPABILITY, False),
            ("InternalServerError", GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True),
            ("ServiceUnavailableError", GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE, True),
            ("BadRequestError", GatewayFailureCategory.VALIDATION_FAILURE, False),
            ("PermissionDeniedError", GatewayFailureCategory.AUTH_FAILURE, False),
        ],
    )
    def test_exception_type_mapping(
        self,
        exc_class_name: str,
        expected_category: GatewayFailureCategory,
        expected_retryable: bool,
    ) -> None:
        exc = _make_exc(exc_class_name, "test")
        category, retryable = _classify_litellm_error(exc)

        assert category is expected_category
        assert retryable is expected_retryable

    def test_unknown_exception_with_status_code(self) -> None:
        exc = _make_exc("SomeUnknownError", "server error", status_code=429)
        category, retryable = _classify_litellm_error(exc)

        assert category is GatewayFailureCategory.RATE_LIMIT
        assert retryable is True

    def test_unknown_exception_falls_through(self) -> None:
        exc = Exception("something unexpected")
        category, retryable = _classify_litellm_error(exc)

        assert category is GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE
        assert retryable is True


class TestLiteLLMUsageExtraction:
    """Tests for _extract_usage helper."""

    def test_standard_usage(self) -> None:
        usage = MagicMock()
        usage.prompt_tokens = 15
        usage.completion_tokens = 7
        result = _extract_usage(usage)

        assert isinstance(result, GatewayUsage)
        assert result.input_tokens == 15
        assert result.output_tokens == 7
