"""Unit tests for the page_renderer module."""

from __future__ import annotations

from pathlib import Path

import pytest

from nullvector.ingest.page_renderer import (
    installed_pymupdf_version,
    open_pdf,
    pdf_page_count,
    render_page_to_png,
    render_pages_to_png,
)

PHASE01_FIXTURES = Path("fixtures/pdfs/phase01")
BORN_DIGITAL = PHASE01_FIXTURES / "born_digital_with_outline.pdf"


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_open_pdf_yields_document_handle() -> None:
    with open_pdf(str(BORN_DIGITAL)) as document:
        assert document.page_count > 0


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_pdf_page_count_returns_positive_integer() -> None:
    count = pdf_page_count(str(BORN_DIGITAL))
    assert isinstance(count, int)
    assert count > 0


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_render_page_to_png_returns_png_bytes() -> None:
    with open_pdf(str(BORN_DIGITAL)) as document:
        page = document.load_page(0)
        png_bytes = render_page_to_png(page, dpi=72)
        assert isinstance(png_bytes, bytes)
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_render_pages_to_png_returns_tuple_of_png_bytes() -> None:
    page_count = pdf_page_count(str(BORN_DIGITAL))
    pages = render_pages_to_png(BORN_DIGITAL, dpi=72)
    assert isinstance(pages, tuple)
    assert len(pages) == page_count
    for png_bytes in pages:
        assert isinstance(png_bytes, bytes)
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_installed_pymupdf_version_returns_nonempty_string() -> None:
    version = installed_pymupdf_version()
    assert isinstance(version, str)
    assert len(version) > 0


def test_open_pdf_raises_on_missing_file() -> None:
    with pytest.raises(RuntimeError), open_pdf("/nonexistent/path/to/file.pdf"):
        pass
