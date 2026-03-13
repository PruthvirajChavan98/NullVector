"""Tesseract-backed OCR helpers via PyMuPDF."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, cast

from nullvector.domain.models import OcrMode, ParserSettings
from nullvector.ingest.errors import MissingOcrRuntimeError


def join_ocr_languages(languages: tuple[str, ...]) -> str:
    """Join OCR languages into PyMuPDF's `eng+spa` format."""

    return "+".join(languages)


def validate_ocr_runtime(
    settings: ParserSettings,
    *,
    document_id: str,
    page_index: int,
) -> None:
    """Validate explicit local OCR runtime requirements for pages that need OCR."""

    if shutil.which("tesseract") is None:
        msg = "Tesseract executable is required for OCR pages"
        raise MissingOcrRuntimeError(msg, page_index=page_index, document_id=document_id)
    if settings.tessdata_path is None:
        msg = "tessdata_path must be configured when OCR is required"
        raise MissingOcrRuntimeError(msg, page_index=page_index, document_id=document_id)

    tessdata_path = Path(settings.tessdata_path)
    if not tessdata_path.exists():
        msg = "configured tessdata_path does not exist"
        raise MissingOcrRuntimeError(msg, page_index=page_index, document_id=document_id)
    if not tessdata_path.is_dir():
        msg = "configured tessdata_path must be a directory"
        raise MissingOcrRuntimeError(msg, page_index=page_index, document_id=document_id)

    for language in settings.ocr_languages:
        traineddata = tessdata_path / f"{language}.traineddata"
        if not traineddata.is_file():
            msg = f"configured tessdata_path is missing {language}.traineddata"
            raise MissingOcrRuntimeError(msg, page_index=page_index, document_id=document_id)


def build_ocr_textpage(
    page: Any,
    settings: ParserSettings,
    *,
    ocr_mode: OcrMode,
    document_id: str,
    page_index: int,
) -> Any:
    """Create an OCR TextPage once so all later extraction reuses it."""

    if ocr_mode == OcrMode.NONE:
        msg = "ocr_mode 'none' cannot build an OCR textpage"
        raise MissingOcrRuntimeError(msg, page_index=page_index, document_id=document_id)

    return page.get_textpage_ocr(
        language=join_ocr_languages(settings.ocr_languages),
        dpi=settings.ocr_dpi,
        full=(ocr_mode == OcrMode.FULL),
        tessdata=settings.tessdata_path,
    )


def extract_ocr_text(page: Any, textpage: Any) -> str:
    """Extract OCR-backed plain text using the OCR TextPage."""

    return cast(str, page.get_text("text", textpage=textpage))


def extract_ocr_rawdict(page: Any, textpage: Any) -> dict[str, Any]:
    """Extract OCR-backed rawdict using the OCR TextPage."""

    return cast(dict[str, Any], page.get_text("rawdict", textpage=textpage))
