"""Unit tests for the Phase 03 LLM gateway core."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel

from nullvector.llm import (
    GatewayAssuranceMode,
    GatewayAuditConfig,
    GatewayAuditRecord,
    GatewayConfig,
    GatewayConfigurationError,
    GatewayFailureCategory,
    GatewayRequest,
    GatewayService,
    GatewaySuccess,
    GatewayUnsupportedCapabilityError,
    GatewayValidationError,
    LLMMessage,
    LLMRole,
    NoopProviderAdapter,
    NoopScriptedResponse,
    StructuredOutputMode,
)
from nullvector.llm.types import (
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
)


class EchoResponse(BaseModel):
    """Simple structured output model for gateway tests."""

    message: str


class StaticRedactionHook:
    """Redact prompt content and raw payloads for audit tests."""

    def redact(self, record: GatewayAuditRecord) -> GatewayAuditRecord:
        redacted_messages = tuple(
            message.model_copy(update={"content": "[redacted]"}) for message in record.messages
        )
        return record.model_copy(
            update={
                "messages": redacted_messages,
                "request_payload": {"redacted": True},
                "response_payload": {"redacted": True},
            },
        )


class SequencedAdapter:
    """Provider adapter that returns a fixed sequence of results."""

    provider_name = "sequenced"

    def __init__(self, results: Sequence[ProviderInvocationResult]) -> None:
        self._results = list(results)
        self.calls = 0

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        del request, config
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
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


def test_gateway_success_returns_validated_model_and_persisted_audit(tmp_path: Path) -> None:
    gateway = GatewayService(
        make_config(tmp_path),
        provider_adapter=NoopProviderAdapter(
            {
                "echo": NoopScriptedResponse(output_json={"message": "hello"}),
            },
        ),
    )

    success = gateway.invoke(make_request(idempotency_key="echo-request"))

    assert success.output.message == "hello"
    assert success.assurance_mode is GatewayAssuranceMode.TRANSPORT_COMPATIBLE
    assert success.audit_path is not None
    persisted = json.loads(Path(success.audit_path).read_text(encoding="utf-8"))
    assert persisted["request_id"] == "echo-request"
    assert persisted["parsed_output"]["message"] == "hello"


def test_gateway_validation_failure_persists_audit_before_exception(tmp_path: Path) -> None:
    gateway = GatewayService(
        make_config(tmp_path),
        provider_adapter=NoopProviderAdapter(
            {
                "echo": NoopScriptedResponse(output_json={"wrong": "shape"}),
            },
        ),
    )

    with pytest.raises(GatewayValidationError) as exc_info:
        gateway.invoke(make_request(idempotency_key="bad-shape"))

    failure = exc_info.value.failure
    assert failure.category is GatewayFailureCategory.VALIDATION_FAILURE
    assert exc_info.value.audit_path is not None
    persisted = json.loads(Path(exc_info.value.audit_path).read_text(encoding="utf-8"))
    assert persisted["failure"]["category"] == GatewayFailureCategory.VALIDATION_FAILURE.value
    assert persisted["request_id"] == "bad-shape"


def test_gateway_applies_redaction_hooks_before_persistence(tmp_path: Path) -> None:
    gateway = GatewayService(
        make_config(tmp_path),
        provider_adapter=NoopProviderAdapter(
            {
                "echo": NoopScriptedResponse(
                    output_json={"message": "hello"},
                    raw_response_payload={"secret": "keep-out"},
                ),
            },
        ),
        redaction_hooks=(StaticRedactionHook(),),
    )

    success = gateway.invoke(make_request(idempotency_key="redacted"))

    persisted = json.loads(Path(success.audit_path or "").read_text(encoding="utf-8"))
    assert persisted["messages"][0]["content"] == "[redacted]"
    assert persisted["request_payload"] == {"redacted": True}
    assert persisted["response_payload"] == {"redacted": True}


def test_gateway_retries_retryable_failures_and_records_delays(tmp_path: Path) -> None:
    sleep_calls: list[float] = []
    adapter = SequencedAdapter(
        [
            ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name="sequenced",
                    model_name="test-model",
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                    category=GatewayFailureCategory.TIMEOUT,
                    message="upstream timed out",
                    retryable=True,
                ),
            ),
            ProviderInvocationResult(
                success=ProviderInvocationSuccess(
                    provider_name="sequenced",
                    model_name="test-model",
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                    structured_output_json={"message": "after retry"},
                    status_code=200,
                ),
            ),
        ],
    )
    gateway = GatewayService(
        make_config(tmp_path),
        provider_adapter=adapter,
        sleep_fn=sleep_calls.append,
    )

    success = gateway.invoke(make_request(idempotency_key="retry-sequence"))

    assert adapter.calls == 2
    assert sleep_calls == [0.25]
    assert len(success.attempts) == 2
    assert success.output.message == "after retry"
    assert success.attempts[0].failure_category is GatewayFailureCategory.TIMEOUT


def test_invoke_many_preserves_input_order(tmp_path: Path) -> None:
    gateway = GatewayService(
        make_config(tmp_path),
        provider_adapter=NoopProviderAdapter(
            {
                "first": NoopScriptedResponse(output_json={"message": "one"}),
                "second": NoopScriptedResponse(output_json={"message": "two"}),
            },
        ),
    )

    results = gateway.invoke_many(
        (
            make_request(operation_name="second", idempotency_key="batch-second"),
            make_request(operation_name="first", idempotency_key="batch-first"),
        ),
        max_workers=2,
    )

    assert [result.output.message for result in results] == ["two", "one"]
    assert all(isinstance(result, GatewaySuccess) for result in results)


def test_invoke_many_raises_first_error_and_persists_each_audit(tmp_path: Path) -> None:
    gateway = GatewayService(
        make_config(tmp_path),
        provider_adapter=NoopProviderAdapter(
            {
                "bad-first": NoopScriptedResponse(output_json={"wrong": "shape"}),
                "good-second": NoopScriptedResponse(output_json={"message": "hello"}),
            },
        ),
    )

    with pytest.raises(GatewayValidationError) as exc_info:
        gateway.invoke_many(
            (
                make_request(operation_name="bad-first", idempotency_key="bad-first"),
                make_request(operation_name="good-second", idempotency_key="good-second"),
            ),
            max_workers=2,
        )

    assert exc_info.value.failure.category is GatewayFailureCategory.VALIDATION_FAILURE
    assert exc_info.value.audit_path is not None
    audit_files = sorted((tmp_path / "audit").glob("*.json"))
    assert [path.name for path in audit_files] == ["bad-first.json", "good-second.json"]


def test_noop_adapter_rejects_unknown_operations(tmp_path: Path) -> None:
    gateway = GatewayService(
        make_config(tmp_path),
        provider_adapter=NoopProviderAdapter({}),
    )

    with pytest.raises(GatewayUnsupportedCapabilityError):
        gateway.invoke(make_request(operation_name="missing-script", idempotency_key="missing"))


def test_unsupported_structured_output_mode_rejected(tmp_path: Path) -> None:
    """Provider-native mode is rejected when config only declares transport-compatible."""
    gateway = GatewayService(
        make_config(tmp_path),
        provider_adapter=NoopProviderAdapter(
            {"echo": NoopScriptedResponse(output_json={"message": "hello"})},
        ),
    )

    with pytest.raises(GatewayConfigurationError, match="does not support structured output mode"):
        gateway.invoke(
            make_request(
                structured_output_mode=StructuredOutputMode.PROVIDER_NATIVE,
                idempotency_key="mode-unsupported",
            ),
        )
