"""Unit tests for attachment-backed requests on the unified gateway."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from nullvector.domain import (
    BoundingBox,
    StructuredRegionInsight,
    VisualEnrichmentRequest,
    VisualRegionReference,
)
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayError,
    GatewayFailureCategory,
    GatewayRequest,
    GatewayService,
    LLMMessage,
    LLMRole,
    NoopProviderAdapter,
    NoopScriptedResponse,
    RegionImageInput,
    VisualInsightResponse,
    enrich_visual_region,
)


def write_attachment(tmp_path: Path, name: str = "region.png") -> Path:
    attachment = tmp_path / name
    attachment.write_bytes(b"png-placeholder")
    return attachment


def make_region(*, asset_path: Path | None = None) -> VisualRegionReference:
    return VisualRegionReference(
        document_id="d" * 64,
        page_index=0,
        region_id="region-001",
        bbox=BoundingBox(x0=0.0, y0=0.0, x1=10.0, y1=10.0),
        image_ref="region-001",
        asset_path=str(asset_path) if asset_path is not None else None,
        node_id="node-001",
    )


def make_gateway(tmp_path: Path, adapter: NoopProviderAdapter) -> GatewayService:
    return GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=adapter,
    )


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        payload = getattr(record, "nullvector_event", None)
        if isinstance(payload, dict):
            self.events.append(payload)


def test_attachment_request_persists_audit_and_validates_success(tmp_path: Path) -> None:
    attachment = write_attachment(tmp_path)
    gateway = make_gateway(
        tmp_path,
        NoopProviderAdapter(
            {
                "visual_region_enrichment": NoopScriptedResponse(
                    output_json={
                        "insight": {
                            "summary": "diagram summary",
                            "labels": ["diagram"],
                            "attributes": {"shape": "block"},
                            "confidence": 0.9,
                        }
                    }
                )
            }
        ),
    )

    success = gateway.invoke(
        GatewayRequest[VisualInsightResponse](
            operation_name="visual_region_enrichment",
            messages=(LLMMessage(role=LLMRole.USER, content="Describe the region"),),
            attachments=(
                RegionImageInput(
                    region=make_region(asset_path=attachment),
                    image_path=str(attachment),
                ),
            ),
            response_model=VisualInsightResponse,
        )
    )

    assert success.output.insight.summary == "diagram summary"
    assert success.audit_path is not None
    assert Path(success.audit_path).exists()


def test_attachment_request_failure_is_typed_and_audited(tmp_path: Path) -> None:
    attachment = write_attachment(tmp_path)
    gateway = make_gateway(
        tmp_path,
        NoopProviderAdapter(
            {
                "visual_region_enrichment": NoopScriptedResponse(
                    failure_category=GatewayFailureCategory.NETWORK_FAILURE,
                    failure_message="network down",
                )
            }
        ),
    )

    with pytest.raises(GatewayError) as exc_info:
        gateway.invoke(
            GatewayRequest[VisualInsightResponse](
                operation_name="visual_region_enrichment",
                messages=(LLMMessage(role=LLMRole.USER, content="Describe the region"),),
                attachments=(
                    RegionImageInput(
                        region=make_region(asset_path=attachment),
                        image_path=str(attachment),
                    ),
                ),
                response_model=VisualInsightResponse,
            )
        )

    assert exc_info.value.failure.category is GatewayFailureCategory.NETWORK_FAILURE
    assert exc_info.value.audit_path is not None
    assert Path(exc_info.value.audit_path or "").exists()


def test_enrich_visual_region_returns_attachment_payload_and_logs_events(tmp_path: Path) -> None:
    attachment_path = write_attachment(tmp_path)
    gateway = make_gateway(
        tmp_path,
        NoopProviderAdapter(
            {
                "visual_region_enrichment": NoopScriptedResponse(
                    output_json={
                        "insight": {
                            "summary": "attachment summary",
                            "labels": ["table"],
                            "attributes": {"rows": 3},
                            "confidence": 0.75,
                        }
                    }
                )
            }
        ),
    )
    logger = logging.getLogger("nullvector.test.visual")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    capture = _CaptureHandler()
    logger.addHandler(capture)

    attachment = enrich_visual_region(
        gateway,
        VisualEnrichmentRequest(
            request_id="attach-001",
            region=make_region(asset_path=attachment_path),
            prompt="Describe the region",
        ),
        logger=logger,
    )

    assert attachment.authoritative is False
    assert attachment.insight == StructuredRegionInsight(
        summary="attachment summary",
        labels=("table",),
        attributes={"rows": 3},
        confidence=0.75,
    )
    assert [str(event["event_name"]) for event in capture.events] == [
        "ExternalEnrichmentRequested",
        "ExternalEnrichmentMerged",
        "VisualEnrichmentAttached",
    ]


def test_attachment_request_rejects_missing_attachment_before_invocation(tmp_path: Path) -> None:
    gateway = make_gateway(
        tmp_path,
        NoopProviderAdapter(
            {
                "visual_region_enrichment": NoopScriptedResponse(
                    output_json={
                        "insight": {
                            "summary": "should never be used",
                            "labels": ["diagram"],
                        }
                    }
                )
            }
        ),
    )

    with pytest.raises(GatewayError) as exc_info:
        gateway.invoke(
            GatewayRequest[VisualInsightResponse](
                operation_name="visual_region_enrichment",
                messages=(LLMMessage(role=LLMRole.USER, content="Describe the region"),),
                attachments=(
                    RegionImageInput(
                        region=make_region(),
                        image_path=str(tmp_path / "missing-region.png"),
                    ),
                ),
                response_model=VisualInsightResponse,
            )
        )

    assert exc_info.value.failure.category is GatewayFailureCategory.VALIDATION_FAILURE
