"""Gateway orchestration and Phase 02 repair integration for Phase 03."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from nullvector.domain.models import RepairDecision, RepairRequest
from nullvector.llm.audit import apply_redaction_hooks, json_safe, persist_audit_record
from nullvector.llm.config_validation import (
    provider_supported_modes,
    validate_gateway_mode_configuration,
)
from nullvector.llm.errors import GatewayConfigurationError, error_from_failure
from nullvector.llm.prompts.repair import RepairPromptResponse, build_repair_messages
from nullvector.llm.protocols import ProviderAdapter, RedactionHook, StructuredLLMGateway
from nullvector.llm.providers.litellm_sdk import LiteLLMSDKAdapter
from nullvector.llm.providers.openai_http import OpenAIResponsesHTTPAdapter
from nullvector.llm.retry import backoff_delay_seconds, should_retry
from nullvector.llm.types import (
    GatewayAttempt,
    GatewayAuditRecord,
    GatewayConfig,
    GatewayFailure,
    GatewayFailureCategory,
    GatewayOutcome,
    GatewayRequest,
    GatewaySuccess,
    JSONValue,
    OpenAIProviderConfig,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    StructuredOutputMode,
)
from nullvector.runtime_validation import validate_writable_root

T = TypeVar("T", bound=BaseModel)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _default_provider_adapter(config: GatewayConfig) -> ProviderAdapter:
    if isinstance(config.provider, OpenAIProviderConfig):
        return OpenAIResponsesHTTPAdapter()
    return LiteLLMSDKAdapter()


def _request_id(request: GatewayRequest[T]) -> str:
    return request.idempotency_key or uuid.uuid4().hex


def _model_name(config: GatewayConfig, request: GatewayRequest[T]) -> str:
    return request.model_name or config.provider.model


def _provider_default_mode(config: GatewayConfig) -> StructuredOutputMode:
    if isinstance(config.provider, OpenAIProviderConfig):
        return StructuredOutputMode.PROVIDER_NATIVE
    return StructuredOutputMode.TRANSPORT_COMPATIBLE


def _effective_structured_output_mode(
    config: GatewayConfig,
    request: GatewayRequest[T],
) -> StructuredOutputMode:
    requested_mode = (
        request.structured_output_mode
        or config.structured_output_mode_preference
        or _provider_default_mode(config)
    )
    if requested_mode not in provider_supported_modes(config):
        msg = (
            f"provider {config.provider.provider} does not support structured output mode "
            f"{requested_mode.value}"
        )
        raise GatewayConfigurationError(msg)
    return requested_mode


def _provider_request(
    config: GatewayConfig,
    request_id: str,
    request: GatewayRequest[T],
) -> ProviderInvocationRequest:
    model = request.response_model
    schema = cast(dict[str, object], model.model_json_schema())
    response_schema = cast(dict[str, JSONValue], json_safe(schema))
    return ProviderInvocationRequest(
        request_id=request_id,
        operation_name=request.operation_name,
        messages=request.messages,
        model_name=_model_name(config, request),
        structured_output_mode=_effective_structured_output_mode(config, request),
        response_model_name=model.__name__,
        response_schema_name=model.__name__,
        response_schema=response_schema,
        timeout_seconds=config.timeout_seconds,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        metadata=request.metadata,
        idempotency_key=request.idempotency_key,
    )


def _build_attempt(
    *,
    attempt_number: int,
    delay_before_attempt_seconds: float,
    result: ProviderInvocationResult,
    started_at: datetime,
    completed_at: datetime,
) -> GatewayAttempt:
    success = result.success
    failure = result.failure
    if success is not None:
        return GatewayAttempt(
            attempt_number=attempt_number,
            provider_name=success.provider_name,
            model_name=success.model_name,
            assurance_mode=success.assurance_mode,
            structured_output_mode=success.structured_output_mode,
            delay_before_attempt_seconds=delay_before_attempt_seconds,
            started_at=started_at,
            completed_at=completed_at,
            usage=success.usage,
            retryable=False,
            status_code=success.status_code,
            provider_request_id=success.provider_request_id,
            provider_response_id=success.provider_response_id,
        )
    assert failure is not None
    return GatewayAttempt(
        attempt_number=attempt_number,
        provider_name=failure.provider_name,
        model_name=failure.model_name,
        assurance_mode=failure.assurance_mode,
        structured_output_mode=failure.structured_output_mode,
        delay_before_attempt_seconds=delay_before_attempt_seconds,
        started_at=started_at,
        completed_at=completed_at,
        failure_category=failure.category,
        failure_message=failure.message,
        retryable=failure.retryable,
        status_code=failure.status_code,
        provider_request_id=failure.provider_request_id,
        provider_response_id=failure.provider_response_id,
    )


def _parse_structured_payload(
    success: ProviderInvocationSuccess,
) -> tuple[object, str]:
    if success.structured_output_json is not None:
        parsed_output = success.structured_output_json
        return parsed_output, json.dumps(json_safe(parsed_output), ensure_ascii=True)
    if success.structured_output_text is not None:
        return (
            cast(object, json.loads(success.structured_output_text)),
            success.structured_output_text,
        )
    msg = "provider returned no structured output payload"
    raise ValueError(msg)


def _validation_failure(
    *,
    request_id: str,
    request: GatewayRequest[T],
    provider_request: ProviderInvocationRequest,
    success: ProviderInvocationSuccess,
    attempts: tuple[GatewayAttempt, ...],
    exc: Exception,
    parsed_output: object | None = None,
) -> GatewayFailure:
    details: dict[str, JSONValue] = {}
    if isinstance(exc, ValidationError):
        details["validation_errors"] = json_safe(exc.errors())
    else:
        details["reason"] = str(exc)
    if parsed_output is not None:
        details["parsed_output"] = json_safe(parsed_output)
    return GatewayFailure(
        request_id=request_id,
        operation_name=request.operation_name,
        category=GatewayFailureCategory.VALIDATION_FAILURE,
        message="structured provider payload failed gateway validation",
        provider_name=success.provider_name,
        model_name=success.model_name,
        assurance_mode=success.assurance_mode,
        structured_output_mode=provider_request.structured_output_mode,
        retryable=False,
        attempt_count=len(attempts),
        status_code=success.status_code,
        provider_request_id=success.provider_request_id,
        provider_response_id=success.provider_response_id,
        details=details,
    )


def _provider_failure_to_gateway_failure(
    *,
    request_id: str,
    request: GatewayRequest[T],
    attempts: tuple[GatewayAttempt, ...],
    failure: ProviderInvocationFailure,
) -> GatewayFailure:
    return GatewayFailure(
        request_id=request_id,
        operation_name=request.operation_name,
        category=failure.category,
        message=failure.message,
        provider_name=failure.provider_name,
        model_name=failure.model_name,
        assurance_mode=failure.assurance_mode,
        structured_output_mode=failure.structured_output_mode,
        retryable=failure.retryable,
        attempt_count=len(attempts),
        status_code=failure.status_code,
        provider_request_id=failure.provider_request_id,
        provider_response_id=failure.provider_response_id,
        provider_error_code=failure.provider_error_code,
        details=failure.details,
    )


class GatewayService(StructuredLLMGateway):
    """Sync-first typed gateway with NullVector-owned retries and auditing."""

    def __init__(
        self,
        config: GatewayConfig,
        *,
        provider_adapter: ProviderAdapter | None = None,
        redaction_hooks: tuple[RedactionHook, ...] = (),
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        validate_gateway_mode_configuration(config)
        validate_writable_root(config.audit.persist_root, label="gateway audit root")
        self._config = config
        self._provider_adapter = provider_adapter or _default_provider_adapter(config)
        self._redaction_hooks = redaction_hooks
        self._sleep_fn = sleep_fn

    def close(self) -> None:
        close_method = getattr(self._provider_adapter, "close", None)
        if callable(close_method):
            close_method()

    def execute(self, request: GatewayRequest[T]) -> GatewayOutcome[T]:
        request_id = _request_id(request)
        provider_request = _provider_request(self._config, request_id, request)
        attempts: list[GatewayAttempt] = []
        delay = 0.0

        for attempt_number in range(1, self._config.retry_policy.max_attempts + 1):
            started_at = _utcnow()
            result = self._provider_adapter.invoke(provider_request, self._config)
            completed_at = _utcnow()
            attempts.append(
                _build_attempt(
                    attempt_number=attempt_number,
                    delay_before_attempt_seconds=delay,
                    result=result,
                    started_at=started_at,
                    completed_at=completed_at,
                ),
            )

            if result.success is not None:
                success = result.success
                try:
                    parsed_output, serialized_output = _parse_structured_payload(success)
                    validated_output = request.response_model.model_validate_json(serialized_output)
                except (ValueError, ValidationError) as exc:
                    failure = _validation_failure(
                        request_id=request_id,
                        request=request,
                        provider_request=provider_request,
                        success=success,
                        attempts=tuple(attempts),
                        exc=exc,
                        parsed_output=locals().get("parsed_output"),
                    )
                    audit_record = GatewayAuditRecord(
                        audit_id=uuid.uuid4().hex,
                        request_id=request_id,
                        operation_name=request.operation_name,
                        provider_name=success.provider_name,
                        model_name=success.model_name,
                        assurance_mode=success.assurance_mode,
                        structured_output_mode=success.structured_output_mode,
                        messages=request.messages,
                        request_payload=(
                            success.raw_request_payload
                            if self._config.audit.capture_raw_request
                            else None
                        ),
                        response_payload=(
                            success.raw_response_payload
                            if self._config.audit.capture_raw_response
                            else None
                        ),
                        parsed_output=locals().get("parsed_output"),
                        failure=failure,
                        attempts=tuple(attempts),
                        metadata=request.metadata,
                    )
                    redacted = apply_redaction_hooks(audit_record, self._redaction_hooks)
                    audit_path = persist_audit_record(
                        redacted,
                        root=self._config.audit.persist_root,
                    )
                    return GatewayOutcome[T](
                        failure=failure,
                        audit_record=redacted,
                        audit_path=audit_path,
                    )

                gateway_success = GatewaySuccess(
                    request_id=request_id,
                    operation_name=request.operation_name,
                    provider_name=success.provider_name,
                    model_name=success.model_name,
                    assurance_mode=success.assurance_mode,
                    structured_output_mode=success.structured_output_mode,
                    output=validated_output,
                    attempts=tuple(attempts),
                    usage=success.usage,
                    provider_request_id=success.provider_request_id,
                    provider_response_id=success.provider_response_id,
                )
                audit_record = GatewayAuditRecord(
                    audit_id=uuid.uuid4().hex,
                    request_id=request_id,
                    operation_name=request.operation_name,
                    provider_name=success.provider_name,
                    model_name=success.model_name,
                    assurance_mode=success.assurance_mode,
                    structured_output_mode=success.structured_output_mode,
                    messages=request.messages,
                    request_payload=(
                        success.raw_request_payload
                        if self._config.audit.capture_raw_request
                        else None
                    ),
                    response_payload=(
                        success.raw_response_payload
                        if self._config.audit.capture_raw_response
                        else None
                    ),
                    parsed_output=json_safe(validated_output),
                    attempts=tuple(attempts),
                    metadata=request.metadata,
                )
                redacted = apply_redaction_hooks(audit_record, self._redaction_hooks)
                audit_path = persist_audit_record(
                    redacted,
                    root=self._config.audit.persist_root,
                )
                return GatewayOutcome[T](
                    success=gateway_success.model_copy(update={"audit_path": audit_path}),
                    audit_record=redacted,
                    audit_path=audit_path,
                )

            assert result.failure is not None
            provider_failure = result.failure
            if should_retry(
                provider_failure.category,
                attempt_number=attempt_number,
                policy=self._config.retry_policy,
            ):
                delay = backoff_delay_seconds(
                    self._config.retry_policy,
                    attempt_number=attempt_number,
                )
                self._sleep_fn(delay)
                continue

            gateway_failure = _provider_failure_to_gateway_failure(
                request_id=request_id,
                request=request,
                attempts=tuple(attempts),
                failure=provider_failure,
            )
            audit_record = GatewayAuditRecord(
                audit_id=uuid.uuid4().hex,
                request_id=request_id,
                operation_name=request.operation_name,
                provider_name=provider_failure.provider_name,
                model_name=provider_failure.model_name,
                assurance_mode=provider_failure.assurance_mode,
                structured_output_mode=provider_failure.structured_output_mode,
                messages=request.messages,
                request_payload=(
                    provider_failure.raw_request_payload
                    if self._config.audit.capture_raw_request
                    else None
                ),
                response_payload=(
                    provider_failure.raw_response_payload
                    if self._config.audit.capture_raw_response
                    else None
                ),
                failure=gateway_failure,
                attempts=tuple(attempts),
                metadata=request.metadata,
            )
            redacted = apply_redaction_hooks(audit_record, self._redaction_hooks)
            audit_path = persist_audit_record(
                redacted,
                root=self._config.audit.persist_root,
            )
            return GatewayOutcome[T](
                failure=gateway_failure,
                audit_record=redacted,
                audit_path=audit_path,
            )

        msg = "gateway retry loop exhausted without producing a result"
        raise RuntimeError(msg)

    def invoke(self, request: GatewayRequest[T]) -> GatewaySuccess[T]:
        outcome = self.execute(request)
        if outcome.success is not None:
            return outcome.success
        assert outcome.failure is not None
        raise error_from_failure(
            outcome.failure,
            audit_record=outcome.audit_record,
            audit_path=outcome.audit_path,
        )


class GatewayRepairEngine:
    """Gateway-backed repair engine that preserves the Phase 02 protocol."""

    def __init__(
        self,
        *,
        config: GatewayConfig,
        provider_adapter: ProviderAdapter | None = None,
        redaction_hooks: tuple[RedactionHook, ...] = (),
        sleep_fn: Callable[[float], None] = time.sleep,
        audit_root: str | None = None,
    ) -> None:
        gateway_config = config
        if audit_root is not None:
            gateway_config = config.model_copy(
                update={
                    "audit": config.audit.model_copy(update={"persist_root": audit_root}),
                },
            )
        self._gateway = GatewayService(
            gateway_config,
            provider_adapter=provider_adapter,
            redaction_hooks=redaction_hooks,
            sleep_fn=sleep_fn,
        )

    def evaluate(
        self,
        requests: tuple[RepairRequest, ...],
    ) -> tuple[RepairDecision, ...]:
        decisions: list[RepairDecision] = []
        for request in requests:
            success = cast(
                GatewaySuccess[RepairPromptResponse],
                self._gateway.invoke(
                    GatewayRequest[RepairPromptResponse](
                        operation_name=f"repair:{request.repair_kind.value}",
                        messages=build_repair_messages(request),
                        response_model=RepairPromptResponse,
                        idempotency_key=request.request_id,
                        metadata={
                            "repair_kind": request.repair_kind.value,
                            "subject_id": request.subject_id,
                        },
                    ),
                ),
            )
            proposal = success.output
            decisions.append(
                RepairDecision(
                    subject_id=request.subject_id,
                    status=proposal.status,
                    repair_kind=request.repair_kind,
                    request_id=request.request_id,
                    message=proposal.message,
                    proposed_title=proposal.proposed_title,
                    resolved_level=proposal.resolved_level,
                    details=request.details,
                ),
            )
        return tuple(decisions)
