"""Typed gateway exceptions surfaced across the public LLM boundary."""

from __future__ import annotations

from strataforge.llm.types import GatewayAuditRecord, GatewayFailure, GatewayFailureCategory


class GatewayError(Exception):
    """Base class for typed gateway failures."""

    def __init__(
        self,
        failure: GatewayFailure,
        *,
        audit_record: GatewayAuditRecord,
        audit_path: str | None,
    ) -> None:
        super().__init__(failure.message)
        self.failure = failure
        self.audit_record = audit_record
        self.audit_path = audit_path


class GatewayValidationError(GatewayError):
    """Validation failure after structured payload parsing."""


class GatewayTimeoutError(GatewayError):
    """Timeout failure."""


class GatewayRateLimitError(GatewayError):
    """Rate-limit failure."""


class GatewayNetworkError(GatewayError):
    """Network transport failure."""


class GatewayProviderRefusalError(GatewayError):
    """Provider refusal or content-filter failure."""


class GatewayContextLengthError(GatewayError):
    """Context length violation."""


class GatewayAuthError(GatewayError):
    """Authentication or authorization failure."""


class GatewayUnsupportedCapabilityError(GatewayError):
    """Unsupported-capability failure."""


class GatewayUnknownProviderError(GatewayError):
    """Unknown or unclassified provider failure."""


def error_from_failure(
    failure: GatewayFailure,
    *,
    audit_record: GatewayAuditRecord,
    audit_path: str | None,
) -> GatewayError:
    """Map a typed failure envelope to the corresponding public exception."""

    error_cls: type[GatewayError]
    match failure.category:
        case GatewayFailureCategory.VALIDATION_FAILURE:
            error_cls = GatewayValidationError
        case GatewayFailureCategory.TIMEOUT:
            error_cls = GatewayTimeoutError
        case GatewayFailureCategory.RATE_LIMIT:
            error_cls = GatewayRateLimitError
        case GatewayFailureCategory.NETWORK_FAILURE:
            error_cls = GatewayNetworkError
        case GatewayFailureCategory.PROVIDER_REFUSAL:
            error_cls = GatewayProviderRefusalError
        case GatewayFailureCategory.CONTEXT_LENGTH_VIOLATION:
            error_cls = GatewayContextLengthError
        case GatewayFailureCategory.AUTH_FAILURE:
            error_cls = GatewayAuthError
        case GatewayFailureCategory.UNSUPPORTED_CAPABILITY:
            error_cls = GatewayUnsupportedCapabilityError
        case GatewayFailureCategory.UNKNOWN_PROVIDER_FAILURE:
            error_cls = GatewayUnknownProviderError
    return error_cls(failure, audit_record=audit_record, audit_path=audit_path)
