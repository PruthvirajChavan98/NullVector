"""Primary v2 acquisition runtime entrypoints."""

from strataforge.ingest.acquisition_service import AcquisitionService, acquire_document
from strataforge.ingest.errors import (
    ExtractionFailureError,
    InvalidSourceError,
    MissingOcrRuntimeError,
    ParseConflictError,
    ParseSubstrateError,
)
from strataforge.ingest.providers import NativePyMuPDFAcquisitionProvider

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
