"""Primary v2 acquisition runtime entrypoints."""

from __future__ import annotations

from nullvector.ingest.errors import (
    ExtractionFailureError,
    InvalidSourceError,
    MissingOcrRuntimeError,
    ParseConflictError,
    ParseSubstrateError,
)

__all__ = [
    "AcquisitionService",
    "ExtractionFailureError",
    "InvalidSourceError",
    "MissingOcrRuntimeError",
    "NativePyMuPDFAcquisitionProvider",
    "ParseConflictError",
    "ParseSubstrateError",
    "acquire_document",
]


def __getattr__(name: str) -> object:
    if name in {"AcquisitionService", "acquire_document"}:
        from nullvector.ingest.acquisition_service import AcquisitionService, acquire_document

        exports = {
            "AcquisitionService": AcquisitionService,
            "acquire_document": acquire_document,
        }
        return exports[name]
    if name == "NativePyMuPDFAcquisitionProvider":
        from nullvector.ingest.providers import NativePyMuPDFAcquisitionProvider

        return NativePyMuPDFAcquisitionProvider
    msg = f"module 'nullvector.ingest' has no attribute {name!r}"
    raise AttributeError(msg)
