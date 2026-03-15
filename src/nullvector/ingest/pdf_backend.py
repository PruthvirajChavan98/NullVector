"""Centralized PyMuPDF backend helpers for ingestion runtimes."""

from __future__ import annotations

from typing import Any

import fitz
from pypdf import __version__ as pypdf_version

PDFDocument = Any
PDFPage = Any
PDFRect = Any


def open_document(path: str) -> PDFDocument:
    """Open one PDF document through the shared backend."""

    return fitz.open(path)  # type: ignore[no-untyped-call]  # fitz has no type stubs


def make_rect(x0: float, y0: float, x1: float, y1: float) -> PDFRect:
    """Construct one backend-native rectangle."""

    return fitz.Rect(x0, y0, x1, y1)  # type: ignore[no-untyped-call]  # fitz has no type stubs


def installed_pymupdf_version() -> str:
    """Return the installed PyMuPDF runtime version."""

    return fitz.VersionBind


def installed_pypdf_version() -> str:
    """Return the installed pypdf runtime version."""

    return pypdf_version


__all__ = [
    "PDFDocument",
    "PDFPage",
    "PDFRect",
    "installed_pymupdf_version",
    "installed_pypdf_version",
    "make_rect",
    "open_document",
]
