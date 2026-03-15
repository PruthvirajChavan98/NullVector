"""LiteLLM attachment-path adapter tests against the unified gateway."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nullvector.domain import BoundingBox, VisualRegionReference
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayError,
    GatewayFailureCategory,
    GatewayRequest,
    GatewayService,
    LiteLLMProviderConfig,
    LLMMessage,
    LLMRole,
    RegionImageInput,
    VisualInsightResponse,
)
from nullvector.llm.providers import LiteLLMSDKAdapter


def _write_attachment(tmp_path: Path) -> Path:
    attachment = tmp_path / "region.png"
    attachment.write_bytes(b"png-fixture")
    return attachment


def _make_region(image_path: Path) -> RegionImageInput:
    return RegionImageInput(
        region=VisualRegionReference(
            document_id="d" * 64,
            page_index=0,
            region_id="region-001",
            bbox=BoundingBox(x0=0.0, y0=0.0, x1=20.0, y1=20.0),
            image_ref="image-001",
            asset_path=str(image_path),
        ),
        image_path=str(image_path),
    )


def _make_gateway(
    tmp_path: Path,
    *,
    completion_callable: Any,
    supports_vision_callable: Any = lambda *_args, **_kwargs: True,
    get_supported_openai_params_callable: Any = lambda *_args, **_kwargs: ["response_format"],
    model_name: str = "openai/gpt-4.1-mini",
    custom_llm_provider: str | None = "openai",
) -> GatewayService:
    adapter = LiteLLMSDKAdapter(
        completion_callable=completion_callable,
        supports_vision_callable=supports_vision_callable,
        get_supported_openai_params_callable=get_supported_openai_params_callable,
    )
    return GatewayService(
        GatewayConfig(
            provider=LiteLLMProviderConfig(
                model=model_name,
                extra_body=(
                    {"custom_llm_provider": custom_llm_provider}
                    if custom_llm_provider is not None
                    else {}
                ),
            ),
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=adapter,
    )


def _request(image_path: Path) -> GatewayRequest[VisualInsightResponse]:
    return GatewayRequest[VisualInsightResponse](
        operation_name="visual_region_enrichment",
        messages=(LLMMessage(role=LLMRole.USER, content="Describe the image region."),),
        attachments=(_make_region(image_path),),
        response_model=VisualInsightResponse,
    )


def test_litellm_attachment_path_returns_typed_success(tmp_path: Path) -> None:
    gateway = _make_gateway(
        tmp_path,
        completion_callable=lambda **_kwargs: {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"insight":{"summary":"diagram summary","labels":["diagram"],'
                            '"attributes":{"kind":"flow"},"confidence":0.8}}'
                        )
                    }
                }
            ],
            "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
        },
    )

    response = gateway.invoke(_request(_write_attachment(tmp_path)))

    assert response.output.insight.summary == "diagram summary"
    assert response.usage is not None
    assert response.usage.total_tokens == 12


def test_litellm_attachment_path_validation_failure_is_typed(tmp_path: Path) -> None:
    gateway = _make_gateway(
        tmp_path,
        completion_callable=lambda **_kwargs: {
            "choices": [{"message": {"content": '{"wrong":"shape"}'}}],
        },
    )

    with pytest.raises(GatewayError) as exc_info:
        gateway.invoke(_request(_write_attachment(tmp_path)))

    assert exc_info.value.failure.category is GatewayFailureCategory.VALIDATION_FAILURE


def test_litellm_attachment_path_rejects_unsupported_response_format(tmp_path: Path) -> None:
    gateway = _make_gateway(
        tmp_path,
        completion_callable=lambda **_kwargs: {},
        get_supported_openai_params_callable=lambda *_args, **_kwargs: ["temperature"],
    )

    with pytest.raises(GatewayError) as exc_info:
        gateway.invoke(_request(_write_attachment(tmp_path)))

    assert exc_info.value.failure.category is GatewayFailureCategory.UNSUPPORTED_CAPABILITY


def test_litellm_attachment_path_attempts_request_when_param_probe_is_inconclusive(
    tmp_path: Path,
) -> None:
    call_state = {"called": False}

    def completion_callable(**_kwargs: Any) -> dict[str, Any]:
        call_state["called"] = True
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"insight":{"summary":"diagram summary","labels":["diagram"],'
                            '"attributes":{"kind":"flow"},"confidence":0.8}}'
                        )
                    }
                }
            ]
        }

    gateway = _make_gateway(
        tmp_path,
        completion_callable=completion_callable,
        get_supported_openai_params_callable=lambda *_args, **_kwargs: None,
    )

    response = gateway.invoke(_request(_write_attachment(tmp_path)))

    assert call_state["called"] is True
    assert response.output.insight.summary == "diagram summary"


def test_litellm_attachment_path_attempts_request_for_openrouter_when_probe_is_negative(
    tmp_path: Path,
) -> None:
    call_state = {"called": False}

    def completion_callable(**_kwargs: Any) -> dict[str, Any]:
        call_state["called"] = True
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"insight":{"summary":"diagram summary","labels":["diagram"],'
                            '"attributes":{"kind":"flow"},"confidence":0.8}}'
                        )
                    }
                }
            ]
        }

    gateway = _make_gateway(
        tmp_path,
        completion_callable=completion_callable,
        supports_vision_callable=lambda *_args, **_kwargs: False,
        model_name="openrouter/google/gemini-3.1-flash-lite-preview",
        custom_llm_provider="openrouter",
    )

    response = gateway.invoke(_request(_write_attachment(tmp_path)))

    assert call_state["called"] is True
    assert response.output.insight.summary == "diagram summary"


def test_litellm_attachment_path_rejects_negative_vision_probe_for_non_openrouter(
    tmp_path: Path,
) -> None:
    gateway = _make_gateway(
        tmp_path,
        completion_callable=lambda **_kwargs: {},
        supports_vision_callable=lambda *_args, **_kwargs: False,
    )

    with pytest.raises(GatewayError) as exc_info:
        gateway.invoke(_request(_write_attachment(tmp_path)))

    assert exc_info.value.failure.category is GatewayFailureCategory.UNSUPPORTED_CAPABILITY


@pytest.mark.parametrize(
    ("exc_type", "status_code", "expected_category"),
    [
        ("APITimeoutError", 408, GatewayFailureCategory.TIMEOUT),
        ("AuthenticationError", 401, GatewayFailureCategory.AUTH_FAILURE),
        ("APIConnectionError", None, GatewayFailureCategory.NETWORK_FAILURE),
    ],
)
def test_litellm_attachment_exception_mapping(
    tmp_path: Path,
    exc_type: str,
    status_code: int | None,
    expected_category: GatewayFailureCategory,
) -> None:
    error_cls = type(exc_type, (Exception,), {"status_code": status_code})

    def completion_callable(**_kwargs: Any) -> dict[str, Any]:
        raise error_cls("adapter failure")

    gateway = _make_gateway(
        tmp_path,
        completion_callable=completion_callable,
    )

    with pytest.raises(GatewayError) as exc_info:
        gateway.invoke(_request(_write_attachment(tmp_path)))

    assert exc_info.value.failure.category is expected_category
