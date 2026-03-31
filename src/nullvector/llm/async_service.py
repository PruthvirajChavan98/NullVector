"""Async typed gateway with shared retry, audit, and circuit-breaker semantics."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from nullvector.llm.circuit_breaker import CircuitBreaker
from nullvector.llm.config_validation import validate_gateway_mode_configuration
from nullvector.llm.errors import error_from_failure
from nullvector.llm.protocols import AsyncProviderAdapter, AsyncStructuredLLMGateway, RedactionHook
from nullvector.llm.service import (
    _CIRCUIT_BREAKER_FAILURE_CATEGORIES,
    _audit_record,
    _build_attempt,
    _candidate_models,
    _circuit_open_failure,
    _effective_structured_output_mode,
    _parse_structured_payload,
    _persist_audit,
    _provider_failure_to_gateway_failure,
    _provider_request,
    _validate_attachments,
    _validation_failure,
)
from nullvector.llm.types import (
    GatewayAssuranceMode,
    GatewayAttempt,
    GatewayAuditRecord,
    GatewayConfig,
    GatewayFailure,
    GatewayFailureCategory,
    GatewayRequest,
    GatewaySuccess,
)
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.runtime_validation import validate_writable_root
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage.protocol import DocumentStore

T = TypeVar("T", bound=BaseModel)


class AsyncGatewayService(AsyncStructuredLLMGateway):
    """Async typed gateway that preserves the sync gateway semantics."""

    def __init__(
        self,
        config: GatewayConfig,
        *,
        provider_adapter: AsyncProviderAdapter,
        redaction_hooks: tuple[RedactionHook, ...] = (),
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
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
        self._circuit_breakers_lock = asyncio.Lock()
        self._audit_executor = ThreadPoolExecutor(max_workers=8)
        if storage is not None or config.audit.persist_root is not None:
            self._audit_store = build_document_store(
                storage,
                default_filesystem_root=config.audit.persist_root or "artifacts/gateway_audit",
            )

    async def _breaker_for_model(self, model_name: str) -> CircuitBreaker:
        async with self._circuit_breakers_lock:
            breaker = self._circuit_breakers.get(model_name)
            if breaker is None:
                breaker = CircuitBreaker(self._config.circuit_breaker)
                self._circuit_breakers[model_name] = breaker
            return breaker

    async def close(self) -> None:
        self._audit_executor.shutdown(wait=False)
        aclose_method = getattr(self._provider_adapter, "aclose", None)
        if callable(aclose_method):
            await aclose_method()
            return
        close_method = getattr(self._provider_adapter, "close", None)
        if callable(close_method):
            maybe_awaitable = close_method()
            if maybe_awaitable is not None and hasattr(maybe_awaitable, "__await__"):
                await cast(Awaitable[None], maybe_awaitable)

    async def _persist_audit_async(
        self,
        audit_record: GatewayAuditRecord,
    ) -> tuple[GatewayAuditRecord, str | None]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._audit_executor,
            lambda: _persist_audit(
                store=self._audit_store,
                config=self._config,
                hooks=self._redaction_hooks,
                audit_record=audit_record,
            ),
        )

    async def _raise_failure_async(
        self,
        failure: GatewayFailure,
        *,
        audit_record: GatewayAuditRecord,
    ) -> None:
        redacted, audit_path = await self._persist_audit_async(audit_record)
        raise error_from_failure(
            failure,
            audit_record=redacted,
            audit_path=audit_path,
        )

    async def invoke(self, request: GatewayRequest[T]) -> GatewaySuccess[T]:
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
            await self._raise_failure_async(failure, audit_record=audit_record)

        attempts: list[GatewayAttempt] = []
        open_models: list[str] = []
        attachment_paths = [attachment.image_path for attachment in request.attachments]
        for candidate_model in candidate_models:
            breaker = await self._breaker_for_model(candidate_model)
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

            provider_request = _provider_request(
                self._config,
                request_id,
                request,
                model_name=candidate_model,
            )
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
                    attachment_count=len(attachment_paths),
                    attachment_paths=attachment_paths,
                )
                started_at = datetime.now(UTC)
                result = await self._provider_adapter.invoke(provider_request, self._config)
                completed_at = datetime.now(UTC)
                latency_ms = round((completed_at - started_at).total_seconds() * 1000)
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
                    breaker.record_success()
                    try:
                        parsed_output, serialized_output = _parse_structured_payload(success)
                        validated_output = request.response_model.model_validate_json(
                            serialized_output
                        )
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
                        await self._raise_failure_async(failure, audit_record=audit_record)

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
                    usage = success.usage
                    log_event(
                        self._logger,
                        "GatewayCallSucceeded",
                        operation_name=request.operation_name,
                        model_name=success.model_name,
                        provider_name=success.provider_name,
                        tokens_in=usage.input_tokens if usage is not None else 0,
                        tokens_out=usage.output_tokens if usage is not None else 0,
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
                            success.raw_request_payload
                            if self._config.audit.capture_raw_request
                            else None
                        ),
                        response_payload=(
                            success.raw_response_payload
                            if self._config.audit.capture_raw_response
                            else None
                        ),
                        parsed_output=validated_output.model_dump(mode="json"),
                    )
                    _, audit_path = await self._persist_audit_async(audit_record)
                    return gateway_success.model_copy(update={"audit_path": audit_path})

                if result.failure is None:
                    msg = (
                        "provider result has neither success nor failure "
                        "(adapter contract violation)"
                    )
                    raise RuntimeError(msg)
                provider_failure = result.failure
                from nullvector.llm.retry import backoff_delay_seconds, should_retry

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
                    await self._sleep_fn(delay)
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
                    latency_ms=latency_ms,
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
                await self._raise_failure_async(gateway_failure, audit_record=audit_record)

        circuit_failure = _circuit_open_failure(
            request_id=request_id,
            request=request,
            provider_name=self._provider_adapter.provider_name,
            model_name=primary_model_name,
            structured_output_mode=structured_output_mode,
            attempts=tuple(attempts),
            candidate_models=candidate_models,
            open_models=tuple(open_models),
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
            attempts=tuple(attempts),
            failure=circuit_failure,
        )
        await self._raise_failure_async(circuit_failure, audit_record=audit_record)
        msg = "gateway retry loop exhausted without producing a result"
        raise RuntimeError(msg)

    async def invoke_many(
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
            return tuple([await self.invoke(request) for request in request_list])

        semaphore = asyncio.Semaphore(worker_count)
        results: list[GatewaySuccess[T] | Exception | None] = [None] * len(request_list)

        async def _invoke_one(index: int, request: GatewayRequest[T]) -> None:
            async with semaphore:
                try:
                    results[index] = await self.invoke(request)
                except Exception as exc:
                    results[index] = exc

        await asyncio.gather(
            *(_invoke_one(index, request) for index, request in enumerate(request_list))
        )
        for result in results:
            if isinstance(result, Exception):
                raise result
            if result is None:
                msg = "gateway task did not produce a result"
                raise RuntimeError(msg)
        return tuple(cast(GatewaySuccess[T], result) for result in results)


__all__ = ["AsyncGatewayService"]
