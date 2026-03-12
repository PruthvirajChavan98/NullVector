"""Deterministic no-network multimodal adapter for tests and local demos."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import model_validator

from strataforge.domain.models import NonEmptyStr, StrataModel
from strataforge.llm.multimodal_gateway.types import (
    JSONValue,
    MultimodalAssuranceMode,
    MultimodalFailureCategory,
    MultimodalGatewayConfig,
    MultimodalUsage,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
)


class NoopMultimodalResponse(StrataModel):
    """Explicit scripted result for the noop multimodal adapter."""

    output_json: dict[str, JSONValue] | None = None
    failure_category: MultimodalFailureCategory | None = None
    failure_message: NonEmptyStr | None = None
    status_code: int | None = None
    usage: MultimodalUsage | None = None
    raw_response_payload: JSONValue | None = None

    @model_validator(mode="after")
    def validate_script(self) -> NoopMultimodalResponse:
        success_path = self.output_json is not None
        failure_path = self.failure_category is not None and self.failure_message is not None
        if success_path == failure_path:
            msg = "noop multimodal responses must define exactly one of success or failure"
            raise ValueError(msg)
        return self


class NoopMultimodalProviderAdapter:
    """Scripted multimodal adapter with no external dependencies."""

    provider_name = "multimodal_noop"

    def __init__(self, scripts: Mapping[str, NoopMultimodalResponse]) -> None:
        self._scripts = dict(scripts)

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: MultimodalGatewayConfig,
    ) -> ProviderInvocationResult:
        del config
        script = self._scripts.get(request.operation_name)
        if script is None:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                    category=MultimodalFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="noop multimodal adapter has no scripted response for the operation",
                    details={"operation_name": request.operation_name},
                )
            )

        if script.failure_category is not None and script.failure_message is not None:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                    category=script.failure_category,
                    message=script.failure_message,
                    status_code=script.status_code,
                    raw_response_payload=script.raw_response_payload,
                )
            )

        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name=self.provider_name,
                model_name=request.model_name,
                assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
                raw_response_payload=(
                    script.raw_response_payload
                    if script.raw_response_payload is not None
                    else script.output_json
                ),
                structured_output_json=script.output_json,
                usage=script.usage,
                status_code=200,
            )
        )


__all__ = [
    "NoopMultimodalProviderAdapter",
    "NoopMultimodalResponse",
]
