"""Deterministic parser substrate entrypoints."""

from strataforge.ingest.errors import (
    ExtractionFailureError,
    InvalidSourceError,
    MissingOcrRuntimeError,
    ParseConflictError,
    ParseSubstrateError,
)
from strataforge.ingest.service import ParserSubstrateService, parse_document

__all__ = [
    "ExtractionFailureError",
    "InvalidSourceError",
    "MissingOcrRuntimeError",
    "ParseConflictError",
    "ParseSubstrateError",
    "ParserSubstrateService",
    "parse_document",
]
