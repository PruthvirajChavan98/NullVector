"""Deterministic no-network provider adapter for tests and notebooks."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import model_validator

from strataforge.domain.models import NonEmptyStr, StrataModel
from strataforge.llm.types import (
    GatewayAssuranceMode,
    GatewayConfig,
    GatewayFailureCategory,
    GatewayUsage,
    JSONValue,
    ProviderInvocationFailure,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    StructuredOutputMode,
)


class NoopScriptedResponse(StrataModel):
    """Explicit scripted result returned by the noop adapter."""

    output_json: dict[str, JSONValue] | None = None
    output_text: NonEmptyStr | None = None
    failure_category: GatewayFailureCategory | None = None
    failure_message: NonEmptyStr | None = None
    status_code: int | None = None
    provider_error_code: NonEmptyStr | None = None
    usage: GatewayUsage | None = None
    raw_response_payload: JSONValue | None = None

    @model_validator(mode="after")
    def validate_script(self) -> NoopScriptedResponse:
        success_path = self.output_json is not None or self.output_text is not None
        failure_path = self.failure_category is not None and self.failure_message is not None
        if success_path == failure_path:
            msg = "noop scripted responses must define exactly one of success or failure"
            raise ValueError(msg)
        return self


class NoopProviderAdapter:
    """Deterministic scripted adapter that never performs network calls."""

    provider_name = "noop"

    def __init__(self, scripts: Mapping[str, NoopScriptedResponse]) -> None:
        self._scripts = dict(scripts)

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        script = self._scripts.get(request.operation_name)
        if script is None:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=request.structured_output_mode,
                    category=GatewayFailureCategory.UNSUPPORTED_CAPABILITY,
                    message="noop adapter has no scripted response for the requested operation",
                    retryable=False,
                    raw_request_payload=request.model_dump(mode="json"),
                    details={"operation_name": request.operation_name},
                ),
            )

        if script.failure_category is not None and script.failure_message is not None:
            return ProviderInvocationResult(
                failure=ProviderInvocationFailure(
                    provider_name=self.provider_name,
                    model_name=request.model_name,
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                    category=script.failure_category,
                    message=script.failure_message,
                    retryable=False,
                    raw_request_payload=request.model_dump(mode="json"),
                    raw_response_payload=script.raw_response_payload,
                    status_code=script.status_code,
                    provider_error_code=script.provider_error_code,
                ),
            )

        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name=self.provider_name,
                model_name=request.model_name,
                assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                raw_request_payload=request.model_dump(mode="json"),
                raw_response_payload=(
                    script.raw_response_payload
                    if script.raw_response_payload is not None
                    else script.output_json
                ),
                structured_output_json=script.output_json,
                structured_output_text=script.output_text,
                usage=script.usage,
                status_code=200,
                provider_response_id=f"noop-{request.request_id}",
            ),
        )
