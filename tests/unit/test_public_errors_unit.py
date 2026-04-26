"""Unit coverage for the public client-facing error translation layer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from nullvector.domain.ledger import ParseErrorCode, ParseFailure
from nullvector.errors import (
    ClientValidationError,
    DocumentNotIndexedError,
    GatewayInvocationError,
    GatewayUnavailableError,
    IngestionError,
    NullVectorError,
    QueryError,
    RetrievalError,
    TreeBuildError,
    translate_error,
)
from nullvector.ingest.errors import ParseSubstrateError
from nullvector.llm.errors import GatewayCircuitOpenError, GatewayNetworkError
from nullvector.llm.types import (
    GatewayAssuranceMode,
    GatewayAuditRecord,
    GatewayFailure,
    GatewayFailureCategory,
    LLMMessage,
    LLMRole,
    StructuredOutputMode,
)
from nullvector.tree import TreeConflictError


def _gateway_failure(
    category: GatewayFailureCategory,
    *,
    message: str = "gateway failure",
) -> GatewayFailure:
    return GatewayFailure(
        request_id="req-123",
        operation_name="client-test",
        category=category,
        message=message,
        provider_name="noop",
        model_name="demo-model",
        assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
        structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
        retryable=False,
        attempt_count=1,
    )


def _gateway_audit_record() -> GatewayAuditRecord:
    return GatewayAuditRecord(
        audit_id="audit-123",
        request_id="req-123",
        operation_name="client-test",
        provider_name="noop",
        model_name="demo-model",
        assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
        structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
        captured_at=datetime.now(UTC),
        messages=(LLMMessage(role=LLMRole.USER, content="hello"),),
        attempts=(),
    )


def test_translate_error_passthrough_for_existing_public_errors() -> None:
    error = DocumentNotIndexedError("missing")

    assert translate_error(error, operation="query") is error


def test_translate_error_maps_validation_errors() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TypeAdapter(int).validate_python("nope")

    translated = translate_error(exc_info.value, operation="validation")

    assert isinstance(translated, ClientValidationError)


def test_translate_error_maps_parse_substrate_failures() -> None:
    error = ParseSubstrateError(
        ParseFailure(
            code=ParseErrorCode.EXTRACTION_FAILED,
            message="broken parse",
            document_id="doc-123",
        )
    )

    translated = translate_error(error, operation="ingest")

    assert isinstance(translated, IngestionError)


def test_translate_error_maps_tree_conflicts() -> None:
    translated = translate_error(TreeConflictError("conflict"), operation="tree")

    assert isinstance(translated, TreeBuildError)


def test_translate_error_maps_circuit_open_to_unavailable() -> None:
    error = GatewayCircuitOpenError(
        _gateway_failure(GatewayFailureCategory.CIRCUIT_OPEN, message="open"),
        audit_record=_gateway_audit_record(),
        audit_path=None,
    )

    translated = translate_error(error, operation="query")

    assert isinstance(translated, GatewayUnavailableError)


def test_translate_error_maps_other_gateway_failures_to_invocation_error() -> None:
    error = GatewayNetworkError(
        _gateway_failure(GatewayFailureCategory.NETWORK_FAILURE, message="network"),
        audit_record=_gateway_audit_record(),
        audit_path=None,
    )

    translated = translate_error(error, operation="query")

    assert isinstance(translated, GatewayInvocationError)


def test_translate_error_uses_operation_specific_value_error_mapping() -> None:
    assert isinstance(translate_error(ValueError("bad query"), operation="query"), QueryError)
    assert isinstance(
        translate_error(ValueError("bad retrieval"), operation="retrieval"),
        RetrievalError,
    )
    assert isinstance(
        translate_error(ValueError("bad input"), operation="validation"),
        ClientValidationError,
    )


def test_translate_error_falls_back_to_public_base_types() -> None:
    translated = translate_error(RuntimeError("unknown"), operation="retrieval")

    assert isinstance(translated, NullVectorError)
    assert isinstance(translated, RetrievalError)
