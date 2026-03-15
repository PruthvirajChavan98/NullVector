"""Attachment-backed visual enrichment helpers built on the main gateway."""

from __future__ import annotations

import uuid
from logging import Logger
from typing import cast

from nullvector.domain.tree import (
    VisualEnrichmentAttachment,
    VisualEnrichmentRequest,
)
from nullvector.llm.errors import GatewayValidationError
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import (
    GatewayAssuranceMode,
    GatewayAuditRecord,
    GatewayFailure,
    GatewayFailureCategory,
    GatewayRequest,
    JSONValue,
    LLMMessage,
    LLMRole,
    RegionImageInput,
    StructuredOutputMode,
    VisualInsightResponse,
)
from nullvector.observability.logging import log_event


def _missing_attachment_error(
    gateway: StructuredLLMGateway,
    request: VisualEnrichmentRequest,
) -> GatewayValidationError:
    provider_name = gateway.__class__.__name__
    failure = GatewayFailure(
        request_id=request.request_id,
        operation_name="visual_region_enrichment",
        category=GatewayFailureCategory.VALIDATION_FAILURE,
        message="visual region is missing a persisted attachment asset",
        provider_name=provider_name,
        model_name="unknown",
        assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
        structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
        retryable=False,
        attempt_count=0,
        details={"region_id": request.region.region_id},
    )
    audit_record = GatewayAuditRecord(
        audit_id=uuid.uuid4().hex,
        request_id=request.request_id,
        operation_name="visual_region_enrichment",
        provider_name=provider_name,
        model_name="unknown",
        assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
        structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
        messages=(
            LLMMessage(
                role=LLMRole.USER,
                content=request.prompt,
            ),
        ),
        failure=failure,
        attempts=(),
        metadata=cast(dict[str, JSONValue], request.metadata),
    )
    return GatewayValidationError(failure, audit_record=audit_record, audit_path=None)


def enrich_visual_region(
    gateway: StructuredLLMGateway,
    request: VisualEnrichmentRequest,
    *,
    logger: Logger | None = None,
) -> VisualEnrichmentAttachment:
    """Enrich one visual region through the shared gateway."""

    attachment_path = request.region.asset_path or request.region.page_render_path
    if attachment_path is None:
        raise _missing_attachment_error(gateway, request)

    log_event(
        logger,
        "ExternalEnrichmentRequested",
        document_id=request.region.document_id,
        request_id=request.request_id,
        region_id=request.region.region_id,
        node_id=request.node_id or request.region.node_id,
    )
    response = gateway.invoke(
        GatewayRequest[VisualInsightResponse](
            operation_name="visual_region_enrichment",
            messages=(LLMMessage(role=LLMRole.USER, content=request.prompt),),
            attachments=(
                RegionImageInput(
                    region=request.region,
                    image_path=attachment_path,
                ),
            ),
            response_model=VisualInsightResponse,
            idempotency_key=request.request_id,
            metadata=cast(dict[str, JSONValue], request.metadata),
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
    log_event(
        logger,
        "ExternalEnrichmentMerged",
        document_id=attachment.document_id,
        attachment_id=attachment.attachment_id,
        region_id=attachment.region_id,
        node_id=attachment.node_id,
    )
    log_event(
        logger,
        "VisualEnrichmentAttached",
        document_id=attachment.document_id,
        attachment_id=attachment.attachment_id,
        region_id=attachment.region_id,
        node_id=attachment.node_id,
    )
    return attachment


__all__ = ["enrich_visual_region"]
