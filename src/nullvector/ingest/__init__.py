"""Primary v2 acquisition runtime entrypoints."""

from nullvector.ingest.acquisition_service import AcquisitionService, acquire_document
from nullvector.ingest.errors import (
    ExtractionFailureError,
    InvalidSourceError,
    MissingOcrRuntimeError,
    ParseConflictError,
    ParseSubstrateError,
)
from nullvector.ingest.providers import NativePyMuPDFAcquisitionProvider

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
