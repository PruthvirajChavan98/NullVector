"""Attachment-only multimodal gateway and enrichment orchestration."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from nullvector.domain.models import (
    VisualEnrichmentAttachment,
    VisualEnrichmentRequest,
)
from nullvector.llm.multimodal_gateway.errors import MultimodalGatewayError
from nullvector.llm.multimodal_gateway.protocols import (
    MultimodalProviderAdapter,
    StructuredMultimodalGateway,
)
from nullvector.llm.multimodal_gateway.providers.noop import NoopMultimodalProviderAdapter
from nullvector.llm.multimodal_gateway.types import (
    JSONValue,
    MultimodalAssuranceMode,
    MultimodalFailureCategory,
    MultimodalGatewayAuditRecord,
    MultimodalGatewayConfig,
    MultimodalGatewayFailure,
    MultimodalGatewayRequest,
    MultimodalGatewaySuccess,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    RegionImageInput,
    VisualInsightResponse,
)
from nullvector.observability import (
    EventBus,
    ExternalEnrichmentMerged,
    ExternalEnrichmentRequested,
    VisualEnrichmentAttached,
)
from nullvector.runtime_validation import validate_attachment_path, validate_writable_root

T = TypeVar("T", bound=BaseModel)


def _json_safe(value: Any) -> JSONValue:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return cast(JSONValue, {str(key): _json_safe(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return cast(JSONValue, [_json_safe(item) for item in value])
    if isinstance(value, str | int | float | bool) or value is None:
        return cast(JSONValue, value)
    return cast(JSONValue, str(value))


def _persist_audit(record: MultimodalGatewayAuditRecord, root: str | None) -> str | None:
    if root is None:
        return None
    destination = Path(root) / f"{record.request_id}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(_json_safe(record), indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    return str(destination)


def _validate_region_inputs(request: MultimodalGatewayRequest[T]) -> None:
    for region in request.regions:
        validate_attachment_path(region.image_path)


def _default_provider_adapter(config: MultimodalGatewayConfig) -> MultimodalProviderAdapter:
    return NoopMultimodalProviderAdapter({})


def _provider_request(
    config: MultimodalGatewayConfig,
    request_id: str,
    request: MultimodalGatewayRequest[T],
) -> ProviderInvocationRequest:
    model = request.response_model
    schema = cast(dict[str, JSONValue], _json_safe(model.model_json_schema()))
    return ProviderInvocationRequest(
        request_id=request_id,
        operation_name=request.operation_name,
        prompt=request.prompt,
        regions=request.regions,
        model_name=request.model_name or config.provider.model,
        response_model_name=model.__name__,
        response_schema=schema,
        metadata=request.metadata,
        idempotency_key=request.idempotency_key,
    )


def _failure_from_invocation(
    request_id: str,
    request: MultimodalGatewayRequest[T],
    failure: ProviderInvocationFailure,
) -> MultimodalGatewayFailure:
    return MultimodalGatewayFailure(
        request_id=request_id,
        operation_name=request.operation_name,
        category=failure.category,
        message=failure.message,
        provider_name=failure.provider_name,
        model_name=failure.model_name,
        assurance_mode=failure.assurance_mode,
        status_code=failure.status_code,
        details=failure.details,
    )


class MultimodalGatewayService(StructuredMultimodalGateway):
    """Typed gateway for region/image-based structured interpretation."""

    def __init__(
        self,
        config: MultimodalGatewayConfig,
        *,
        provider_adapter: MultimodalProviderAdapter | None = None,
    ) -> None:
        self._config = config
        validate_writable_root(config.audit_root, label="multimodal audit root")
        self._provider_adapter = provider_adapter or _default_provider_adapter(config)

    def invoke(self, request: MultimodalGatewayRequest[T]) -> MultimodalGatewaySuccess[T]:
        request_id = request.idempotency_key or uuid.uuid4().hex
        try:
            _validate_region_inputs(request)
        except ValueError as exc:
            failure = MultimodalGatewayFailure(
                request_id=request_id,
                operation_name=request.operation_name,
                category=MultimodalFailureCategory.INVALID_ATTACHMENT,
                message=str(exc),
                provider_name=self._provider_adapter.provider_name,
                model_name=request.model_name or self._config.provider.model,
                assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
            )
            audit_record = MultimodalGatewayAuditRecord(
                audit_id=uuid.uuid4().hex,
                request_id=request_id,
                operation_name=request.operation_name,
                provider_name=self._provider_adapter.provider_name,
                model_name=request.model_name or self._config.provider.model,
                assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                prompt=request.prompt,
                regions=request.regions,
                failure=failure,
                metadata=request.metadata,
            )
            audit_path = _persist_audit(audit_record, self._config.audit_root)
            raise MultimodalGatewayError(
                failure,
                audit_record=audit_record,
                audit_path=audit_path,
            ) from exc
        provider_request = _provider_request(self._config, request_id, request)
        result = self._provider_adapter.invoke(provider_request, self._config)

        if result.failure is not None:
            failure = _failure_from_invocation(request_id, request, result.failure)
            audit_record = MultimodalGatewayAuditRecord(
                audit_id=uuid.uuid4().hex,
                request_id=request_id,
                operation_name=request.operation_name,
                provider_name=result.failure.provider_name,
                model_name=result.failure.model_name,
                assurance_mode=result.failure.assurance_mode,
                prompt=request.prompt,
                regions=request.regions,
                response_payload=result.failure.raw_response_payload,
                failure=failure,
                metadata=request.metadata,
            )
            audit_path = _persist_audit(audit_record, self._config.audit_root)
            raise MultimodalGatewayError(
                failure,
                audit_record=audit_record,
                audit_path=audit_path,
            )

        assert result.success is not None
        try:
            payload = result.success.structured_output_json
            if payload is None:
                msg = "multimodal provider returned no structured output payload"
                raise ValueError(msg)
            validated = request.response_model.model_validate_json(
                json.dumps(_json_safe(payload), ensure_ascii=True)
            )
        except (ValidationError, ValueError) as exc:
            failure = MultimodalGatewayFailure(
                request_id=request_id,
                operation_name=request.operation_name,
                category=MultimodalFailureCategory.VALIDATION_FAILURE,
                message="multimodal provider payload failed validation",
                provider_name=result.success.provider_name,
                model_name=result.success.model_name,
                assurance_mode=result.success.assurance_mode,
                status_code=result.success.status_code,
                details={"reason": str(exc)},
            )
            audit_record = MultimodalGatewayAuditRecord(
                audit_id=uuid.uuid4().hex,
                request_id=request_id,
                operation_name=request.operation_name,
                provider_name=result.success.provider_name,
                model_name=result.success.model_name,
                assurance_mode=result.success.assurance_mode,
                prompt=request.prompt,
                regions=request.regions,
                response_payload=result.success.raw_response_payload,
                parsed_output=result.success.structured_output_json,
                failure=failure,
                metadata=request.metadata,
            )
            audit_path = _persist_audit(audit_record, self._config.audit_root)
            raise MultimodalGatewayError(
                failure,
                audit_record=audit_record,
                audit_path=audit_path,
            ) from exc

        audit_record = MultimodalGatewayAuditRecord(
            audit_id=uuid.uuid4().hex,
            request_id=request_id,
            operation_name=request.operation_name,
            provider_name=result.success.provider_name,
            model_name=result.success.model_name,
            assurance_mode=result.success.assurance_mode,
            prompt=request.prompt,
            regions=request.regions,
            response_payload=result.success.raw_response_payload,
            parsed_output=_json_safe(validated),
            metadata=request.metadata,
        )
        audit_path = _persist_audit(audit_record, self._config.audit_root)
        return MultimodalGatewaySuccess[T](
            request_id=request_id,
            operation_name=request.operation_name,
            provider_name=result.success.provider_name,
            model_name=result.success.model_name,
            assurance_mode=result.success.assurance_mode,
            output=validated,
            usage=result.success.usage,
            audit_path=audit_path,
        )


class VisualEnrichmentService:
    """Attachment-only orchestration for committed-node visual enrichment."""

    def __init__(
        self,
        gateway: StructuredMultimodalGateway,
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self._gateway = gateway
        self._event_bus = event_bus

    def enrich(self, request: VisualEnrichmentRequest) -> VisualEnrichmentAttachment:
        attachment_path = request.region.asset_path or request.region.page_render_path
        if attachment_path is None:
            failure = MultimodalGatewayFailure(
                request_id=request.request_id,
                operation_name="visual_region_enrichment",
                category=MultimodalFailureCategory.INVALID_ATTACHMENT,
                message="visual region is missing a persisted attachment asset",
                provider_name=self._gateway.__class__.__name__,
                model_name="unknown",
                assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                details={"region_id": request.region.region_id},
            )
            audit_record = MultimodalGatewayAuditRecord(
                audit_id=uuid.uuid4().hex,
                request_id=request.request_id,
                operation_name="visual_region_enrichment",
                provider_name=self._gateway.__class__.__name__,
                model_name="unknown",
                assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                prompt=request.prompt,
                regions=(),
                failure=failure,
                metadata=cast(dict[str, JSONValue], _json_safe(request.metadata)),
            )
            raise MultimodalGatewayError(
                failure,
                audit_record=audit_record,
                audit_path=None,
            )
        if self._event_bus is not None:
            self._event_bus.publish(
                ExternalEnrichmentRequested(
                    event_id=f"{request.request_id}-requested",
                    event_name="ExternalEnrichmentRequested",
                    document_id=request.region.document_id,
                    request_id=request.request_id,
                    region_id=request.region.region_id,
                    node_id=request.node_id or request.region.node_id,
                )
            )
        response = self._gateway.invoke(
            MultimodalGatewayRequest[VisualInsightResponse](
                operation_name="visual_region_enrichment",
                prompt=request.prompt,
                regions=(
                    RegionImageInput(
                        region=request.region,
                        image_path=attachment_path,
                    ),
                ),
                response_model=VisualInsightResponse,
                idempotency_key=request.request_id,
                metadata=cast(dict[str, JSONValue], _json_safe(request.metadata)),
            )
        )
        attachment = VisualEnrichmentAttachment(
            attachment_id=request.request_id,
            document_id=request.region.document_id,
            node_id=request.node_id or request.region.node_id,
            region_id=request.region.region_id,
            provider_identity=response.provider_name,
            confidence=response.output.insight.confidence,
            authoritative=False,
            insight=response.output.insight,
            audit_path=response.audit_path,
        )
        if self._event_bus is not None:
            self._event_bus.publish(
                ExternalEnrichmentMerged(
                    event_id=f"{attachment.attachment_id}-merged",
                    event_name="ExternalEnrichmentMerged",
                    document_id=attachment.document_id,
                    attachment_id=attachment.attachment_id,
                    region_id=attachment.region_id,
                    node_id=attachment.node_id,
                )
            )
            self._event_bus.publish(
                VisualEnrichmentAttached(
                    event_id=f"{attachment.attachment_id}-attached",
                    event_name="VisualEnrichmentAttached",
                    document_id=attachment.document_id,
                    attachment_id=attachment.attachment_id,
                    region_id=attachment.region_id,
                    node_id=attachment.node_id,
                )
            )
        return attachment


__all__ = [
    "MultimodalGatewayService",
    "VisualEnrichmentService",
]
