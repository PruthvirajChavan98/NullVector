"""Framework-owned providers for the parallel v2 acquisition runtime."""

from nullvector.ingest.providers.markdown_native import MarkdownNativeAcquisitionProvider
from nullvector.ingest.providers.native_pymupdf import NativePyMuPDFAcquisitionProvider

__all__ = [
    "MarkdownNativeAcquisitionProvider",
    "NativePyMuPDFAcquisitionProvider",
]
