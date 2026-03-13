"""Unit tests for the attachment-only multimodal gateway."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nullvector.domain import (
    BoundingBox,
    StructuredRegionInsight,
    VisualEnrichmentRequest,
    VisualRegionReference,
)
from nullvector.llm.multimodal_gateway import (
    MultimodalFailureCategory,
    MultimodalGatewayConfig,
    MultimodalGatewayError,
    MultimodalGatewayRequest,
    MultimodalGatewayService,
    MultimodalProviderConfig,
    NoopMultimodalProviderAdapter,
    NoopMultimodalResponse,
    RegionImageInput,
    VisualEnrichmentService,
    VisualInsightResponse,
)
from nullvector.observability import EventBus


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


def make_gateway(
    tmp_path: Path, adapter: NoopMultimodalProviderAdapter
) -> MultimodalGatewayService:
    return MultimodalGatewayService(
        MultimodalGatewayConfig(
            provider=MultimodalProviderConfig(model="test-multimodal"),
            audit_root=str(tmp_path / "audit"),
        ),
        provider_adapter=adapter,
    )


def test_multimodal_request_requires_at_least_one_region() -> None:
    with pytest.raises(ValidationError):
        MultimodalGatewayRequest[VisualInsightResponse](
            operation_name="visual_region_enrichment",
            prompt="Describe the region",
            regions=(),
            response_model=VisualInsightResponse,
        )


def test_multimodal_gateway_persists_audit_and_validates_success(tmp_path: Path) -> None:
    attachment = write_attachment(tmp_path)
    gateway = make_gateway(
        tmp_path,
        NoopMultimodalProviderAdapter(
            {
                "visual_region_enrichment": NoopMultimodalResponse(
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
        MultimodalGatewayRequest[VisualInsightResponse](
            operation_name="visual_region_enrichment",
            prompt="Describe the region",
            regions=(
                RegionImageInput(
                    region=make_region(asset_path=attachment),
                    image_path=str(attachment),
                ),
            ),
            response_model=VisualInsightResponse,
        )
    )

    assert success.assurance_mode.value == "attachment_only"
    assert success.output.insight.summary == "diagram summary"
    assert success.audit_path is not None
    assert Path(success.audit_path).exists()


def test_multimodal_gateway_failure_is_typed_and_audited(tmp_path: Path) -> None:
    attachment = write_attachment(tmp_path)
    gateway = make_gateway(
        tmp_path,
        NoopMultimodalProviderAdapter(
            {
                "visual_region_enrichment": NoopMultimodalResponse(
                    failure_category=MultimodalFailureCategory.NETWORK_FAILURE,
                    failure_message="network down",
                )
            }
        ),
    )

    with pytest.raises(MultimodalGatewayError) as exc_info:
        gateway.invoke(
            MultimodalGatewayRequest[VisualInsightResponse](
                operation_name="visual_region_enrichment",
                prompt="Describe the region",
                regions=(
                    RegionImageInput(
                        region=make_region(asset_path=attachment),
                        image_path=str(attachment),
                    ),
                ),
                response_model=VisualInsightResponse,
            )
        )

    assert exc_info.value.failure.category is MultimodalFailureCategory.NETWORK_FAILURE
    assert exc_info.value.audit_path is not None
    assert Path(exc_info.value.audit_path or "").exists()


def test_visual_enrichment_service_returns_attachment_only_payload(tmp_path: Path) -> None:
    attachment_path = write_attachment(tmp_path)
    gateway = make_gateway(
        tmp_path,
        NoopMultimodalProviderAdapter(
            {
                "visual_region_enrichment": NoopMultimodalResponse(
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
    event_bus = EventBus()
    service = VisualEnrichmentService(gateway, event_bus=event_bus)

    attachment = service.enrich(
        VisualEnrichmentRequest(
            request_id="attach-001",
            region=make_region(asset_path=attachment_path),
            prompt="Describe the region",
        )
    )

    assert attachment.authoritative is False
    assert attachment.insight == StructuredRegionInsight(
        summary="attachment summary",
        labels=("table",),
        attributes={"rows": 3},
        confidence=0.75,
    )
    assert [event.event_name for event in event_bus.published_events] == [
        "ExternalEnrichmentRequested",
        "ExternalEnrichmentMerged",
        "VisualEnrichmentAttached",
    ]


def test_multimodal_gateway_rejects_missing_attachment_before_invocation(
    tmp_path: Path,
) -> None:
    gateway = make_gateway(
        tmp_path,
        NoopMultimodalProviderAdapter(
            {
                "visual_region_enrichment": NoopMultimodalResponse(
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

    with pytest.raises(MultimodalGatewayError) as exc_info:
        gateway.invoke(
            MultimodalGatewayRequest[VisualInsightResponse](
                operation_name="visual_region_enrichment",
                prompt="Describe the region",
                regions=(
                    RegionImageInput(
                        region=make_region(),
                        image_path=str(tmp_path / "missing-region.png"),
                    ),
                ),
                response_model=VisualInsightResponse,
            )
        )

    assert exc_info.value.failure.category is MultimodalFailureCategory.INVALID_ATTACHMENT
