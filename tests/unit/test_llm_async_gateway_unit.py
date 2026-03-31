"""Unit tests for the async typed LLM gateway."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel

from nullvector.llm import (
    AsyncGatewayService,
    CircuitBreakerConfig,
    GatewayAuditConfig,
    GatewayCircuitOpenError,
    GatewayConfig,
    GatewayFailureCategory,
    GatewayRequest,
    GatewayRetryPolicy,
    GatewaySuccess,
    GatewayTimeoutError,
    LLMMessage,
    LLMRole,
    StructuredOutputMode,
)
from nullvector.llm.types import (
    GatewayAssuranceMode,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
)


class EchoResponse(BaseModel):
    """Simple structured output model for async gateway tests."""

    message: str


class AsyncOperationAdapter:
    """Async provider adapter keyed by operation name."""

    provider_name = "async-operation"

    def __init__(self, results_by_operation: dict[str, Sequence[ProviderInvocationResult]]) -> None:
        self._results_by_operation = {
            operation: list(results) for operation, results in results_by_operation.items()
        }
        self._calls_by_operation = {operation: 0 for operation in results_by_operation}

    async def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        del config
        results = self._results_by_operation[request.operation_name]
        call_count = self._calls_by_operation[request.operation_name]
        result = results[min(call_count, len(results) - 1)]
        self._calls_by_operation[request.operation_name] += 1
        return result


class AsyncModelAwareAdapter:
    """Async provider adapter keyed by requested model."""

    provider_name = "async-model-aware"

    def __init__(self, results_by_model: dict[str, Sequence[ProviderInvocationResult]]) -> None:
        self._results_by_model = {
            model: list(results) for model, results in results_by_model.items()
        }
        self._calls_by_model = {model: 0 for model in results_by_model}
        self.requested_models: list[str] = []

    async def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        del config
        self.requested_models.append(request.model_name)
        results = self._results_by_model[request.model_name]
        call_count = self._calls_by_model[request.model_name]
        result = results[min(call_count, len(results) - 1)]
        self._calls_by_model[request.model_name] += 1
        return result


def make_request(
    *,
    operation_name: str = "echo",
    structured_output_mode: StructuredOutputMode | None = None,
    idempotency_key: str | None = None,
) -> GatewayRequest[EchoResponse]:
    return GatewayRequest[EchoResponse](
        operation_name=operation_name,
        messages=(LLMMessage(role=LLMRole.USER, content="Echo hello"),),
        response_model=EchoResponse,
        idempotency_key=idempotency_key,
        structured_output_mode=structured_output_mode,
    )


def make_config(tmp_path: Path) -> GatewayConfig:
    return GatewayConfig(
        default_model="test-model",
        audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
    )


def make_success_result(*, model_name: str, message: str) -> ProviderInvocationResult:
    return ProviderInvocationResult(
        success=ProviderInvocationSuccess(
            provider_name="async-model-aware",
            model_name=model_name,
            assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
            structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
            structured_output_json={"message": message},
            status_code=200,
            provider_response_id=f"{model_name}-response",
        )
    )


def make_failure_result(
    *,
    model_name: str,
    category: GatewayFailureCategory,
    message: str,
    retryable: bool = True,
) -> ProviderInvocationResult:
    return ProviderInvocationResult(
        failure=ProviderInvocationFailure(
            provider_name="async-model-aware",
            model_name=model_name,
            assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
            structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
            category=category,
            message=message,
            retryable=retryable,
        )
    )


@pytest.mark.asyncio
async def test_async_gateway_success_returns_validated_model_and_persisted_audit(
    tmp_path: Path,
) -> None:
    gateway = AsyncGatewayService(
        make_config(tmp_path),
        provider_adapter=AsyncOperationAdapter(
            {"echo": (make_success_result(model_name="test-model", message="hello"),)}
        ),
    )

    success = await gateway.invoke(make_request(idempotency_key="async-echo-request"))

    assert success.output.message == "hello"
    assert success.assurance_mode is GatewayAssuranceMode.TRANSPORT_COMPATIBLE
    assert success.audit_path is not None
    persisted = json.loads(Path(success.audit_path).read_text(encoding="utf-8"))
    assert persisted["request_id"] == "async-echo-request"
    assert persisted["parsed_output"]["message"] == "hello"


@pytest.mark.asyncio
async def test_async_invoke_many_preserves_input_order(tmp_path: Path) -> None:
    gateway = AsyncGatewayService(
        make_config(tmp_path),
        provider_adapter=AsyncOperationAdapter(
            {
                "first": (make_success_result(model_name="test-model", message="one"),),
                "second": (make_success_result(model_name="test-model", message="two"),),
            }
        ),
    )

    results = await gateway.invoke_many(
        (
            make_request(operation_name="second", idempotency_key="batch-second"),
            make_request(operation_name="first", idempotency_key="batch-first"),
        ),
        max_workers=2,
    )

    assert [result.output.message for result in results] == ["two", "one"]
    assert all(isinstance(result, GatewaySuccess) for result in results)


@pytest.mark.asyncio
async def test_async_invoke_many_raises_first_error_and_persists_each_audit(tmp_path: Path) -> None:
    gateway = AsyncGatewayService(
        make_config(tmp_path),
        provider_adapter=AsyncOperationAdapter(
            {
                "bad-first": (
                    ProviderInvocationResult(
                        success=ProviderInvocationSuccess(
                            provider_name="async-operation",
                            model_name="test-model",
                            assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                            structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                            structured_output_json={"wrong": "shape"},
                            status_code=200,
                        )
                    ),
                ),
                "good-second": (make_success_result(model_name="test-model", message="hello"),),
            }
        ),
    )

    with pytest.raises(Exception) as exc_info:
        await gateway.invoke_many(
            (
                make_request(operation_name="bad-first", idempotency_key="bad-first"),
                make_request(operation_name="good-second", idempotency_key="good-second"),
            ),
            max_workers=2,
        )

    assert type(exc_info.value).__name__ == "GatewayValidationError"
    audit_files = sorted((tmp_path / "audit").glob("*.json"))
    assert [path.name for path in audit_files] == ["bad-first.json", "good-second.json"]


@pytest.mark.asyncio
async def test_async_gateway_uses_fallback_model_when_primary_circuit_is_open(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path).model_copy(
        update={
            "fallback_models": ("fallback-model",),
            "retry_policy": GatewayRetryPolicy(max_attempts=1),
            "circuit_breaker": CircuitBreakerConfig(failure_threshold=1),
        }
    )
    adapter = AsyncModelAwareAdapter(
        {
            "test-model": (
                make_failure_result(
                    model_name="test-model",
                    category=GatewayFailureCategory.TIMEOUT,
                    message="timed out",
                ),
            ),
            "fallback-model": (
                make_success_result(model_name="fallback-model", message="fallback worked"),
            ),
        }
    )
    gateway = AsyncGatewayService(config, provider_adapter=adapter)

    with pytest.raises(GatewayTimeoutError):
        await gateway.invoke(make_request(idempotency_key="primary-failure"))

    success = await gateway.invoke(make_request(idempotency_key="fallback-success"))

    assert success.model_name == "fallback-model"
    assert success.output.message == "fallback worked"
    assert adapter.requested_models == ["test-model", "fallback-model"]


@pytest.mark.asyncio
async def test_async_gateway_raises_circuit_open_when_all_models_are_open(tmp_path: Path) -> None:
    config = make_config(tmp_path).model_copy(
        update={
            "fallback_models": ("fallback-model",),
            "circuit_breaker": CircuitBreakerConfig(failure_threshold=1),
        }
    )
    adapter = AsyncModelAwareAdapter(
        {
            "test-model": (make_success_result(model_name="test-model", message="unused"),),
            "fallback-model": (make_success_result(model_name="fallback-model", message="unused"),),
        }
    )
    gateway = AsyncGatewayService(config, provider_adapter=adapter)
    (await gateway._breaker_for_model("test-model")).record_failure()
    (await gateway._breaker_for_model("fallback-model")).record_failure()

    with pytest.raises(GatewayCircuitOpenError):
        await gateway.invoke(make_request(idempotency_key="all-open"))

    assert adapter.requested_models == []
