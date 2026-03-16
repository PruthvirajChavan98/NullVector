"""Gateway orchestration and prompt-specific helpers for Phase 03."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from nullvector.domain.tree import RepairDecision, RepairRequest
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
    GatewayAssuranceMode,
    GatewayAttempt,
    GatewayAuditRecord,
    GatewayConfig,
    GatewayFailure,
    GatewayFailureCategory,
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
from nullvector.observability.logging import log_event
from nullvector.runtime_validation import (
    validate_attachment_path,
    validate_writable_root,
)
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage.protocol import DocumentStore

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
        attachments=request.attachments,
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


def _audit_record(
    *,
    request: GatewayRequest[T],
    request_id: str,
    provider_name: str,
    model_name: str,
    assurance_mode: GatewayAssuranceMode,
    structured_output_mode: StructuredOutputMode,
    attempts: tuple[GatewayAttempt, ...],
    request_payload: JSONValue | None = None,
    response_payload: JSONValue | None = None,
    parsed_output: JSONValue | None = None,
    failure: GatewayFailure | None = None,
) -> GatewayAuditRecord:
    return GatewayAuditRecord(
        audit_id=uuid.uuid4().hex,
        request_id=request_id,
        operation_name=request.operation_name,
        provider_name=provider_name,
        model_name=model_name,
        assurance_mode=assurance_mode,
        structured_output_mode=structured_output_mode,
        messages=request.messages,
        attachments=request.attachments,
        request_payload=request_payload,
        response_payload=response_payload,
        parsed_output=parsed_output,
        failure=failure,
        attempts=attempts,
        metadata=request.metadata,
    )


def _persist_audit(
    *,
    store: DocumentStore | None,
    config: GatewayConfig,
    hooks: tuple[RedactionHook, ...],
    audit_record: GatewayAuditRecord,
) -> tuple[GatewayAuditRecord, str | None]:
    redacted = apply_redaction_hooks(audit_record, hooks)
    if store is None:
        audit_path = persist_audit_record(redacted, root=config.audit.persist_root)
    else:
        audit_path = store.append_audit(redacted)
    return redacted, audit_path


def _raise_failure(
    failure: GatewayFailure,
    *,
    store: DocumentStore | None,
    config: GatewayConfig,
    hooks: tuple[RedactionHook, ...],
    audit_record: GatewayAuditRecord,
) -> None:
    redacted, audit_path = _persist_audit(
        store=store,
        config=config,
        hooks=hooks,
        audit_record=audit_record,
    )
    raise error_from_failure(
        failure,
        audit_record=redacted,
        audit_path=audit_path,
    )


def _validate_attachments(
    request_id: str,
    request: GatewayRequest[T],
    *,
    provider_name: str,
    model_name: str,
    structured_output_mode: StructuredOutputMode,
) -> tuple[GatewayFailure, GatewayAuditRecord] | None:
    try:
        for attachment in request.attachments:
            validate_attachment_path(attachment.image_path)
    except ValueError as exc:
        failure = GatewayFailure(
            request_id=request_id,
            operation_name=request.operation_name,
            category=GatewayFailureCategory.VALIDATION_FAILURE,
            message=str(exc),
            provider_name=provider_name,
            model_name=model_name,
            assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
            structured_output_mode=structured_output_mode,
            retryable=False,
            attempt_count=0,
            details={"attachment_count": len(request.attachments)},
        )
        audit_record = GatewayAuditRecord(
            audit_id=uuid.uuid4().hex,
            request_id=request_id,
            operation_name=request.operation_name,
            provider_name=provider_name,
            model_name=model_name,
            assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
            structured_output_mode=structured_output_mode,
            messages=request.messages,
            attachments=request.attachments,
            failure=failure,
            attempts=(),
            metadata=request.metadata,
        )
        return failure, audit_record
    return None


class GatewayService(StructuredLLMGateway):
    """Sync-first typed gateway with NullVector-owned retries and auditing."""

    def __init__(
        self,
        config: GatewayConfig,
        *,
        provider_adapter: ProviderAdapter | None = None,
        redaction_hooks: tuple[RedactionHook, ...] = (),
        sleep_fn: Callable[[float], None] = time.sleep,
        storage: StorageConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        validate_gateway_mode_configuration(config)
        if storage is None:
            validate_writable_root(config.audit.persist_root, label="gateway audit root")
        self._config = config
        self._provider_adapter = provider_adapter or _default_provider_adapter(config)
        self._redaction_hooks = redaction_hooks
        self._sleep_fn = sleep_fn
        self._logger = logger
        self._audit_store: DocumentStore | None = None
        if storage is not None or config.audit.persist_root is not None:
            self._audit_store = build_document_store(
                storage,
                default_filesystem_root=config.audit.persist_root or "artifacts/gateway_audit",
            )

    def close(self) -> None:
        close_method = getattr(self._provider_adapter, "close", None)
        if callable(close_method):
            close_method()

    def invoke(self, request: GatewayRequest[T]) -> GatewaySuccess[T]:
        request_id = _request_id(request)
        structured_output_mode = _effective_structured_output_mode(self._config, request)
        attachment_failure = _validate_attachments(
            request_id,
            request,
            provider_name=self._provider_adapter.provider_name,
            model_name=_model_name(self._config, request),
            structured_output_mode=structured_output_mode,
        )
        if attachment_failure is not None:
            failure, audit_record = attachment_failure
            _raise_failure(
                failure,
                store=self._audit_store,
                config=self._config,
                hooks=self._redaction_hooks,
                audit_record=audit_record,
            )
        provider_request = _provider_request(self._config, request_id, request)
        attempts: list[GatewayAttempt] = []
        delay = 0.0

        _attachment_paths = [a.image_path for a in request.attachments]
        for attempt_number in range(1, self._config.retry_policy.max_attempts + 1):
            log_event(
                self._logger,
                "GatewayCallAttempted",
                operation_name=request.operation_name,
                model_name=provider_request.model_name,
                provider_name=self._provider_adapter.provider_name,
                attempt_number=attempt_number,
                max_attempts=self._config.retry_policy.max_attempts,
                attachment_count=len(_attachment_paths),
                attachment_paths=_attachment_paths,
            )
            started_at = _utcnow()
            result = self._provider_adapter.invoke(provider_request, self._config)
            completed_at = _utcnow()
            _latency_ms = round((completed_at - started_at).total_seconds() * 1000)
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
                    log_event(
                        self._logger,
                        "GatewayCallFailed",
                        operation_name=request.operation_name,
                        model_name=success.model_name,
                        provider_name=success.provider_name,
                        failure_category=GatewayFailureCategory.VALIDATION_FAILURE.value,
                        message=failure.message,
                        retryable=False,
                        attempt_number=attempt_number,
                        latency_ms=_latency_ms,
                    )
                    audit_record = _audit_record(
                        request=request,
                        request_id=request_id,
                        provider_name=success.provider_name,
                        model_name=success.model_name,
                        assurance_mode=success.assurance_mode,
                        structured_output_mode=success.structured_output_mode,
                        attempts=tuple(attempts),
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
                    )
                    _raise_failure(
                        failure,
                        store=self._audit_store,
                        config=self._config,
                        hooks=self._redaction_hooks,
                        audit_record=audit_record,
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
                _usage = success.usage
                log_event(
                    self._logger,
                    "GatewayCallSucceeded",
                    operation_name=request.operation_name,
                    model_name=success.model_name,
                    provider_name=success.provider_name,
                    tokens_in=_usage.input_tokens if _usage is not None else 0,
                    tokens_out=_usage.output_tokens if _usage is not None else 0,
                    latency_ms=_latency_ms,
                    attempt_number=attempt_number,
                )
                audit_record = _audit_record(
                    request=request,
                    request_id=request_id,
                    provider_name=success.provider_name,
                    model_name=success.model_name,
                    assurance_mode=success.assurance_mode,
                    structured_output_mode=success.structured_output_mode,
                    attempts=tuple(attempts),
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
                )
                redacted, audit_path = _persist_audit(
                    store=self._audit_store,
                    config=self._config,
                    hooks=self._redaction_hooks,
                    audit_record=audit_record,
                )
                del redacted
                return gateway_success.model_copy(update={"audit_path": audit_path})

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
            log_event(
                self._logger,
                "GatewayCallFailed",
                operation_name=request.operation_name,
                model_name=provider_failure.model_name,
                provider_name=provider_failure.provider_name,
                failure_category=provider_failure.category.value,
                message=provider_failure.message,
                retryable=provider_failure.retryable,
                attempt_number=attempt_number,
                latency_ms=_latency_ms,
            )
            audit_record = _audit_record(
                request=request,
                request_id=request_id,
                provider_name=provider_failure.provider_name,
                model_name=provider_failure.model_name,
                assurance_mode=provider_failure.assurance_mode,
                structured_output_mode=provider_failure.structured_output_mode,
                attempts=tuple(attempts),
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
            )
            _raise_failure(
                gateway_failure,
                store=self._audit_store,
                config=self._config,
                hooks=self._redaction_hooks,
                audit_record=audit_record,
            )

        msg = "gateway retry loop exhausted without producing a result"
        raise RuntimeError(msg)


def evaluate_repairs(
    gateway: StructuredLLMGateway,
    requests: tuple[RepairRequest, ...],
) -> tuple[RepairDecision, ...]:
    """Evaluate bounded repair requests through a structured gateway."""

    decisions: list[RepairDecision] = []
    for request in requests:
        success = cast(
            GatewaySuccess[RepairPromptResponse],
            gateway.invoke(
                GatewayRequest[RepairPromptResponse](
                    operation_name=f"repair:{request.repair_kind.value}",
                    messages=build_repair_messages(request),
                    response_model=RepairPromptResponse,
                    idempotency_key=request.request_id,
                    metadata={
                        "repair_kind": request.repair_kind.value,
                        "subject_id": request.subject_id,
                    },
                )
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
            )
        )
    return tuple(decisions)


__all__ = ["GatewayService", "evaluate_repairs"]
