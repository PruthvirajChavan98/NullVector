"""Thin PyMuPDF wrapper for page-to-PNG rendering."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import fitz


@contextmanager
def open_pdf(source_path: str) -> Iterator[Any]:
    """Open a PDF document and yield the PyMuPDF document handle."""

    document = fitz.open(source_path)  # type: ignore[no-untyped-call]
    try:
        yield document
    finally:
        document.close()  # type: ignore[no-untyped-call]


def pdf_page_count(source_path: str) -> int:
    """Return the page count for a PDF source."""

    with open_pdf(source_path) as document:
        return int(document.page_count)


def render_page_to_png(page: Any, *, dpi: int = 150) -> bytes:
    """Render one PyMuPDF page to PNG bytes."""

    return cast(bytes, page.get_pixmap(dpi=dpi, annots=False).tobytes("png"))


def render_pages_to_png(source_path: str | Path, *, dpi: int = 150) -> tuple[bytes, ...]:
    """Render every page of a PDF to PNG bytes."""

    path = str(Path(source_path).resolve())
    with open_pdf(path) as document:
        return tuple(
            render_page_to_png(document.load_page(page_index), dpi=dpi)
            for page_index in range(document.page_count)
        )


def installed_pymupdf_version() -> str:
    """Return the installed PyMuPDF version string."""

    return str(fitz.version[0])


__all__ = [
    "installed_pymupdf_version",
    "open_pdf",
    "pdf_page_count",
    "render_page_to_png",
    "render_pages_to_png",
]
