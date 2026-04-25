"""Gateway orchestration and prompt-specific helpers for Phase 03."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from nullvector.llm.audit import apply_redaction_hooks, json_safe, persist_audit_record
from nullvector.llm.circuit_breaker import CircuitBreaker
from nullvector.llm.config_validation import (
    provider_supported_modes,
    validate_gateway_mode_configuration,
)
from nullvector.llm.errors import GatewayConfigurationError, error_from_failure
from nullvector.llm.protocols import ProviderAdapter, RedactionHook, StructuredLLMGateway
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
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    StructuredOutputMode,
    TextGatewayRequest,
    TextGatewaySuccess,
)
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.runtime_validation import (
    validate_attachment_path,
    validate_writable_root,
)
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage.protocol import DocumentStore

T = TypeVar("T", bound=BaseModel)
_CIRCUIT_BREAKER_FAILURE_CATEGORIES = frozenset(
    {
        GatewayFailureCategory.TIMEOUT,
        GatewayFailureCategory.NETWORK_FAILURE,
        GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE,
    }
)


def _effective_structured_output_mode(
    config: GatewayConfig,
    request: GatewayRequest[T],
) -> StructuredOutputMode:
    requested_mode = (
        request.structured_output_mode
        or config.structured_output_mode_preference
        or config.supported_structured_output_modes[0]
    )
    if requested_mode not in provider_supported_modes(config):
        msg = f"configured provider does not support structured output mode {requested_mode.value}"
        raise GatewayConfigurationError(msg)
    return requested_mode


def _enforce_all_required(schema: dict[str, object]) -> dict[str, object]:
    """Make every property required for strict JSON schema providers (Groq, OpenAI strict).

    Strict mode requires ``required`` to list every key in ``properties``.
    Pydantic omits fields with defaults from ``required``, which causes
    provider-side validation errors.
    """
    schema = dict(schema)
    props = schema.get("properties")
    if isinstance(props, dict):
        schema["required"] = sorted(props.keys())
    raw_defs = schema.get("$defs")
    if isinstance(raw_defs, dict):
        schema["$defs"] = {
            name: _enforce_all_required(defn) if isinstance(defn, dict) else defn
            for name, defn in raw_defs.items()
        }
    return schema


def _provider_request(
    config: GatewayConfig,
    request_id: str,
    request: GatewayRequest[T],
    *,
    model_name: str | None = None,
) -> ProviderInvocationRequest:
    model = request.response_model
    schema = cast(dict[str, object], model.model_json_schema())
    response_schema = cast(dict[str, JSONValue], json_safe(_enforce_all_required(schema)))
    return ProviderInvocationRequest(
        request_id=request_id,
        operation_name=request.operation_name,
        messages=request.messages,
        attachments=request.attachments,
        model_name=model_name or request.model_name or config.default_model,
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
    if failure is None:
        msg = "provider result has neither success nor failure (adapter contract violation)"
        raise RuntimeError(msg)
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


def _candidate_models(
    config: GatewayConfig,
    request: GatewayRequest[T],
) -> tuple[str, ...]:
    primary_model = request.model_name or config.default_model
    return tuple(dict.fromkeys((primary_model, *config.fallback_models)))


def _circuit_open_failure(
    *,
    request_id: str,
    request: GatewayRequest[T],
    provider_name: str,
    model_name: str,
    structured_output_mode: StructuredOutputMode,
    attempts: tuple[GatewayAttempt, ...],
    candidate_models: tuple[str, ...],
    open_models: tuple[str, ...],
) -> GatewayFailure:
    return GatewayFailure(
        request_id=request_id,
        operation_name=request.operation_name,
        category=GatewayFailureCategory.CIRCUIT_OPEN,
        message="all configured model circuits are open for this request",
        provider_name=provider_name,
        model_name=model_name,
        assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
        structured_output_mode=structured_output_mode,
        retryable=False,
        attempt_count=len(attempts),
        details={
            "candidate_models": list(candidate_models),
            "open_models": list(open_models),
        },
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
        provider_adapter: ProviderAdapter,
        redaction_hooks: tuple[RedactionHook, ...] = (),
        sleep_fn: Callable[[float], None] = time.sleep,
        storage: StorageConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        validate_gateway_mode_configuration(config)
        if storage is None:
            validate_writable_root(config.audit.persist_root, label="gateway audit root")
        self._config = config
        self._provider_adapter = provider_adapter
        self._redaction_hooks = redaction_hooks
        self._sleep_fn = sleep_fn
        self._logger = resolve_runtime_logger(logger)
        self._audit_store: DocumentStore | None = None
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._circuit_breakers_lock = threading.Lock()
        if storage is not None or config.audit.persist_root is not None:
            self._audit_store = build_document_store(
                storage,
                default_filesystem_root=config.audit.persist_root or "artifacts/gateway_audit",
            )

    def _breaker_for_model(self, model_name: str) -> CircuitBreaker:
        with self._circuit_breakers_lock:
            breaker = self._circuit_breakers.get(model_name)
            if breaker is None:
                breaker = CircuitBreaker(self._config.circuit_breaker)
                self._circuit_breakers[model_name] = breaker
            return breaker

    def close(self) -> None:
        close_method = getattr(self._provider_adapter, "close", None)
        if callable(close_method):
            close_method()

    def invoke(self, request: GatewayRequest[T]) -> GatewaySuccess[T]:
        request_id = request.idempotency_key or uuid.uuid4().hex
        structured_output_mode = _effective_structured_output_mode(self._config, request)
        candidate_models = _candidate_models(self._config, request)
        primary_model_name = candidate_models[0]
        attachment_failure = _validate_attachments(
            request_id,
            request,
            provider_name=self._provider_adapter.provider_name,
            model_name=primary_model_name,
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
        attempts: list[GatewayAttempt] = []
        open_models: list[str] = []

        for candidate_model in candidate_models:
            breaker = self._breaker_for_model(candidate_model)
            if not breaker.allow_request():
                open_models.append(candidate_model)
                log_event(
                    self._logger,
                    "GatewayCircuitOpenSkipped",
                    operation_name=request.operation_name,
                    model_name=candidate_model,
                    provider_name=self._provider_adapter.provider_name,
                )
                continue

            result = self._invoke_with_retries(
                request=request,
                request_id=request_id,
                candidate_model=candidate_model,
                breaker=breaker,
                attempts=attempts,
            )
            if result is not None:
                return result

        self._raise_circuit_open(
            request=request,
            request_id=request_id,
            primary_model_name=primary_model_name,
            structured_output_mode=structured_output_mode,
            attempts=tuple(attempts),
            candidate_models=candidate_models,
            open_models=tuple(open_models),
        )
        msg = "gateway retry loop exhausted without producing a result"
        raise RuntimeError(msg)

    def _invoke_with_retries(
        self,
        *,
        request: GatewayRequest[T],
        request_id: str,
        candidate_model: str,
        breaker: CircuitBreaker,
        attempts: list[GatewayAttempt],
    ) -> GatewaySuccess[T] | None:
        """Run the retry loop for one candidate model.

        Returns ``GatewaySuccess`` on success, ``None`` when retries are
        exhausted (caller should try the next candidate), or raises on
        non-retryable failure.
        """
        provider_request = _provider_request(
            self._config,
            request_id,
            request,
            model_name=candidate_model,
        )
        _attachment_paths = [a.image_path for a in request.attachments]
        delay = 0.0
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
            started_at = datetime.now(UTC)
            result = self._provider_adapter.invoke(provider_request, self._config)
            completed_at = datetime.now(UTC)
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
                return self._handle_success(
                    request=request,
                    request_id=request_id,
                    provider_request=provider_request,
                    success=result.success,
                    attempts=attempts,
                    breaker=breaker,
                    attempt_number=attempt_number,
                    latency_ms=_latency_ms,
                )

            if result.failure is None:
                msg = "provider result has neither success nor failure (adapter contract violation)"
                raise RuntimeError(msg)
            provider_failure = result.failure
            if should_retry(
                provider_failure.category,
                attempt_number=attempt_number,
                policy=self._config.retry_policy,
            ):
                if provider_failure.category in _CIRCUIT_BREAKER_FAILURE_CATEGORIES:
                    breaker.record_failure()
                delay = backoff_delay_seconds(
                    self._config.retry_policy,
                    attempt_number=attempt_number,
                )
                self._sleep_fn(delay)
                continue

            if provider_failure.category in _CIRCUIT_BREAKER_FAILURE_CATEGORIES:
                breaker.record_failure()
            else:
                breaker.record_success()

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
        return None

    def _handle_success(
        self,
        *,
        request: GatewayRequest[T],
        request_id: str,
        provider_request: ProviderInvocationRequest,
        success: ProviderInvocationSuccess,
        attempts: list[GatewayAttempt],
        breaker: CircuitBreaker,
        attempt_number: int,
        latency_ms: int,
    ) -> GatewaySuccess[T]:
        """Validate, audit, and return a successful provider response."""
        breaker.record_success()
        parsed_output: object | None = None
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
                parsed_output=parsed_output,
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
                latency_ms=latency_ms,
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
                    success.raw_request_payload if self._config.audit.capture_raw_request else None
                ),
                response_payload=(
                    success.raw_response_payload
                    if self._config.audit.capture_raw_response
                    else None
                ),
                parsed_output=json_safe(parsed_output) if parsed_output is not None else None,
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
            latency_ms=latency_ms,
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
                success.raw_request_payload if self._config.audit.capture_raw_request else None
            ),
            response_payload=(
                success.raw_response_payload if self._config.audit.capture_raw_response else None
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

    def _raise_circuit_open(
        self,
        *,
        request: GatewayRequest[T],
        request_id: str,
        primary_model_name: str,
        structured_output_mode: StructuredOutputMode,
        attempts: tuple[GatewayAttempt, ...],
        candidate_models: tuple[str, ...],
        open_models: tuple[str, ...],
    ) -> None:
        """Log and raise when all candidate models have open circuits."""
        circuit_failure = _circuit_open_failure(
            request_id=request_id,
            request=request,
            provider_name=self._provider_adapter.provider_name,
            model_name=primary_model_name,
            structured_output_mode=structured_output_mode,
            attempts=attempts,
            candidate_models=candidate_models,
            open_models=open_models,
        )
        log_event(
            self._logger,
            "GatewayCallFailed",
            operation_name=request.operation_name,
            model_name=primary_model_name,
            provider_name=self._provider_adapter.provider_name,
            failure_category=GatewayFailureCategory.CIRCUIT_OPEN.value,
            message=circuit_failure.message,
            retryable=False,
            attempt_number=0,
            latency_ms=0,
        )
        audit_record = _audit_record(
            request=request,
            request_id=request_id,
            provider_name=self._provider_adapter.provider_name,
            model_name=primary_model_name,
            assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
            structured_output_mode=structured_output_mode,
            attempts=attempts,
            failure=circuit_failure,
        )
        _raise_failure(
            circuit_failure,
            store=self._audit_store,
            config=self._config,
            hooks=self._redaction_hooks,
            audit_record=audit_record,
        )

    def invoke_many(
        self,
        requests: Sequence[GatewayRequest[T]],
        *,
        max_workers: int | None = None,
    ) -> tuple[GatewaySuccess[T], ...]:
        request_list = tuple(requests)
        if not request_list:
            return ()
        if max_workers is not None and max_workers < 1:
            msg = "max_workers must be greater than or equal to 1"
            raise ValueError(msg)

        worker_count = min(len(request_list), max_workers or 32)
        if worker_count == 1:
            return tuple(self.invoke(request) for request in request_list)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = tuple(executor.submit(self.invoke, request) for request in request_list)

        results: list[GatewaySuccess[T] | None] = [None] * len(request_list)
        first_error: Exception | None = None
        for index, future in enumerate(futures):
            try:
                results[index] = future.result()
            except Exception as exc:
                if first_error is None:
                    first_error = exc

        if first_error is not None:
            raise first_error

        return tuple(cast(GatewaySuccess[T], result) for result in results)

    def invoke_text(self, request: TextGatewayRequest) -> TextGatewaySuccess:
        """Invoke the provider and return raw text — no JSON schema enforcement.

        Uses the same retry, circuit-breaker, and audit machinery as
        ``invoke``, but sends no ``response_format`` and returns the raw
        content string instead of parsing structured output.
        """
        request_id = request.idempotency_key or uuid.uuid4().hex
        candidate_models = (request.model_name or self._config.default_model,)
        primary_model = candidate_models[0]

        # Build a ProviderInvocationRequest with response_schema=None
        # so the adapter skips response_format entirely.
        provider_request = ProviderInvocationRequest(
            request_id=request_id,
            operation_name=request.operation_name,
            messages=request.messages,
            attachments=request.attachments,
            model_name=primary_model,
            structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
            timeout_seconds=self._config.timeout_seconds,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            metadata=request.metadata,
            idempotency_key=request.idempotency_key,
        )

        breaker = self._breaker_for_model(primary_model)
        if not breaker.allow_request():
            msg = f"circuit open for model {primary_model}"
            raise RuntimeError(msg)

        attempts: list[GatewayAttempt] = []
        delay = 0.0

        for attempt_number in range(1, self._config.retry_policy.max_attempts + 1):
            log_event(
                self._logger,
                "GatewayCallAttempted",
                operation_name=request.operation_name,
                model_name=primary_model,
                provider_name=self._provider_adapter.provider_name,
                attempt_number=attempt_number,
                max_attempts=self._config.retry_policy.max_attempts,
                mode="text",
            )
            started_at = datetime.now(UTC)

            result = self._provider_adapter.invoke(provider_request, self._config)

            completed_at = datetime.now(UTC)
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
                breaker.record_success()
                content = result.success.structured_output_text or (
                    json.dumps(result.success.structured_output_json)
                    if result.success.structured_output_json is not None
                    else ""
                )
                log_event(
                    self._logger,
                    "GatewayCallSucceeded",
                    operation_name=request.operation_name,
                    model_name=primary_model,
                    provider_name=self._provider_adapter.provider_name,
                    latency_ms=_latency_ms,
                    attempt_number=attempt_number,
                    mode="text",
                )
                return TextGatewaySuccess(
                    request_id=request_id,
                    operation_name=request.operation_name,
                    provider_name=result.success.provider_name,
                    model_name=result.success.model_name,
                    text=content,
                    attempts=tuple(attempts),
                    usage=(result.success.usage if hasattr(result.success, "usage") else None),
                )

            if result.failure is None:
                msg = "provider returned neither success nor failure"
                raise RuntimeError(msg)

            failure = result.failure
            if should_retry(
                failure.category,
                attempt_number=attempt_number,
                policy=self._config.retry_policy,
            ):
                if failure.category in _CIRCUIT_BREAKER_FAILURE_CATEGORIES:
                    breaker.record_failure()
                delay = backoff_delay_seconds(
                    self._config.retry_policy,
                    attempt_number=attempt_number,
                )
                self._sleep_fn(delay)
                continue

            breaker.record_failure()
            gateway_failure = _provider_failure_to_gateway_failure(
                request_id=request_id,
                request=GatewayRequest(
                    operation_name=request.operation_name,
                    messages=request.messages,
                    attachments=request.attachments,
                    response_model=type(None),
                    metadata=request.metadata,
                ),
                attempts=tuple(attempts),
                failure=failure,
            )
            raise error_from_failure(gateway_failure)

        msg = "text gateway retry loop exhausted"
        raise RuntimeError(msg)


__all__ = ["GatewayService"]
