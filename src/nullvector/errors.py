"""Public error surface for the NullVector client and CLI layers."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from nullvector.ingest.errors import ParseSubstrateError
from nullvector.llm.errors import (
    GatewayCircuitOpenError,
    GatewayConfigurationError,
    GatewayError,
)
from nullvector.tree import TreeConflictError, TreePipelineError

OperationType = Literal["validation", "ingest", "tree", "retrieval", "query"]


class NullVectorError(Exception):
    """Base class for actionable public NullVector exceptions."""


class ClientValidationError(NullVectorError):
    """Raised when user-facing inputs or presets fail validation."""


class IngestionError(NullVectorError):
    """Raised when document acquisition fails."""


class TreeBuildError(NullVectorError):
    """Raised when tree synthesis fails."""


class RetrievalError(NullVectorError):
    """Raised when retrieval or description artifacts cannot be built or loaded."""


class QueryError(NullVectorError):
    """Raised when search or QA execution cannot complete."""


class GatewayInvocationError(QueryError):
    """Raised when one gateway-backed operation fails."""


class GatewayUnavailableError(QueryError):
    """Raised when the configured gateway cannot currently serve requests."""


class DocumentNotIndexedError(QueryError):
    """Raised when the client cannot resolve retrieval artifacts for one document."""


def translate_error(exc: Exception, *, operation: OperationType) -> NullVectorError:
    """Translate one internal failure into the public client-facing hierarchy."""

    if isinstance(exc, NullVectorError):
        return exc
    if isinstance(exc, GatewayCircuitOpenError):
        return GatewayUnavailableError(str(exc))
    if isinstance(exc, GatewayConfigurationError):
        return GatewayUnavailableError(str(exc))
    if isinstance(exc, GatewayError):
        return GatewayInvocationError(str(exc))
    if isinstance(exc, ValidationError):
        return ClientValidationError(str(exc))
    if isinstance(exc, ParseSubstrateError):
        return IngestionError(str(exc))
    if isinstance(exc, TreeConflictError | TreePipelineError):
        return TreeBuildError(str(exc))
    if isinstance(exc, ValueError):
        if operation == "validation":
            return ClientValidationError(str(exc))
        if operation == "ingest":
            return IngestionError(str(exc))
        if operation == "tree":
            return TreeBuildError(str(exc))
        if operation == "retrieval":
            return RetrievalError(str(exc))
        return QueryError(str(exc))
    if operation == "ingest":
        return IngestionError(str(exc))
    if operation == "tree":
        return TreeBuildError(str(exc))
    if operation == "retrieval":
        return RetrievalError(str(exc))
    if operation == "query":
        return QueryError(str(exc))
    return ClientValidationError(str(exc))


__all__ = [
    "ClientValidationError",
    "DocumentNotIndexedError",
    "GatewayInvocationError",
    "GatewayUnavailableError",
    "IngestionError",
    "NullVectorError",
    "QueryError",
    "RetrievalError",
    "TreeBuildError",
    "translate_error",
]
