"""Native page analysis and OCR-needed classification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from nullvector.domain.ledger import OcrMode, ParserSettings


@dataclass(frozen=True)
class PageAnalysis:
    """Observed native-page signals used to decide whether OCR is worthwhile."""

    native_text: str
    native_rawdict: dict[str, Any]
    native_text_sha256: str
    native_word_count: int
    native_char_count: int
    has_text_blocks: bool
    image_coverage_ratio: float
    vector_path_count: int
    dense_small_vector_count: int


@dataclass(frozen=True)
class OcrDecision:
    """Deterministic OCR-needed decision for a page."""

    needs_ocr: bool
    ocr_mode: OcrMode
    reason_codes: tuple[str, ...]


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _page_area(page: Any) -> float:
    return float(page.rect.width * page.rect.height)


def _image_coverage_ratio(page: Any) -> float:
    """Approximate image coverage by summed image bounding boxes clamped to page area.

    Overlapping or transformed images can overcount before the final clamp, so this is a
    heuristic signal for OCR gating rather than a physical coverage measurement.
    """

    page_area = _page_area(page)
    if page_area <= 0:
        return 0.0

    coverage = 0.0
    for image_info in page.get_image_info():
        bbox = image_info.get("bbox")
        if bbox is None:
            continue
        if hasattr(bbox, "width") and hasattr(bbox, "height"):
            coverage += float(bbox.width * bbox.height)
            continue
        if isinstance(bbox, tuple) and len(bbox) == 4:
            x0, y0, x1, y1 = bbox
            coverage += float(max(0.0, x1 - x0) * max(0.0, y1 - y0))
    return min(1.0, coverage / page_area)


def _dense_small_vector_counts(page: Any, settings: ParserSettings) -> tuple[int, int]:
    page_area = _page_area(page)
    if page_area <= 0:
        return 0, 0

    dense_small_vector_count = 0
    vector_path_count = 0
    for drawing in page.get_drawings():
        vector_path_count += 1
        if vector_path_count > settings.vector_scan_limit:
            break
        rect = drawing.get("rect")
        if rect is None:
            continue
        ratio = float(rect.width * rect.height) / page_area
        if ratio <= settings.small_vector_max_area_ratio:
            dense_small_vector_count += 1
    return vector_path_count, dense_small_vector_count


def analyze_native_page(page: Any, settings: ParserSettings) -> PageAnalysis:
    """Collect native extraction signals for OCR classification and persistence."""

    native_text = page.get_text("text")
    native_rawdict = page.get_text("rawdict")
    words = page.get_text("words")
    text_blocks = [
        block
        for block in native_rawdict.get("blocks", [])
        if isinstance(block, dict) and block.get("type") == 0
    ]
    vector_path_count, dense_small_vector_count = _dense_small_vector_counts(page, settings)

    return PageAnalysis(
        native_text=native_text,
        native_rawdict=native_rawdict,
        native_text_sha256=_hash_text(native_text),
        native_word_count=len(words),
        native_char_count=len("".join(native_text.split())),
        has_text_blocks=bool(text_blocks),
        image_coverage_ratio=_image_coverage_ratio(page),
        vector_path_count=vector_path_count,
        dense_small_vector_count=dense_small_vector_count,
    )


def classify_ocr_need(analysis: PageAnalysis, settings: ParserSettings) -> OcrDecision:
    """Decide whether OCR is needed using a bounded multi-signal heuristic."""

    no_text = analysis.native_char_count == 0 and not analysis.has_text_blocks
    low_text_density = (
        analysis.native_char_count < settings.min_text_chars
        or analysis.native_word_count < settings.min_word_count
    )
    high_image_coverage = analysis.image_coverage_ratio >= settings.high_image_coverage_ratio
    near_full_image_coverage = (
        analysis.image_coverage_ratio >= settings.full_page_image_coverage_ratio
    )
    dense_small_vectors = analysis.dense_small_vector_count >= settings.dense_small_vector_threshold

    reason_codes: list[str] = []
    if no_text:
        reason_codes.append("no_text")
    if low_text_density:
        reason_codes.append("low_text_density")
    if high_image_coverage:
        reason_codes.append("high_image_coverage")
    if dense_small_vectors:
        reason_codes.append("dense_small_vectors_heuristic")

    needs_ocr = False
    ocr_mode = OcrMode.NONE
    ocr_positive_signal = high_image_coverage or dense_small_vectors
    if (no_text and ocr_positive_signal) or (low_text_density and ocr_positive_signal):
        needs_ocr = True

    if needs_ocr:
        if no_text and (near_full_image_coverage or dense_small_vectors):
            ocr_mode = OcrMode.FULL
        else:
            ocr_mode = OcrMode.PARTIAL

    return OcrDecision(
        needs_ocr=needs_ocr,
        ocr_mode=ocr_mode,
        reason_codes=tuple(reason_codes) if needs_ocr else (),
    )
