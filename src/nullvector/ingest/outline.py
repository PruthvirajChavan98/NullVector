"""Outline extraction, normalization, and scoring."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pypdf import PdfReader

from nullvector.domain.models import OutlineEntry, OutlineQualityReport, OutlineSource


def _normalize_title(title: str | None) -> str:
    return (title or "").strip()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def extract_pymupdf_outlines(document: Any) -> tuple[list[Any], list[OutlineEntry]]:
    """Return rich and normalized outline representations from PyMuPDF."""

    rich_outline = _json_safe(document.get_toc(False))
    normalized: list[OutlineEntry] = []
    for level, title, page_number in document.get_toc():
        page_index = page_number - 1 if page_number > 0 else None
        normalized.append(
            OutlineEntry(
                level=level,
                title=_normalize_title(title),
                page_index=page_index,
                source=OutlineSource.PYMUPDF,
            ),
        )
    return rich_outline, normalized


def serialize_pypdf_outline(reader: PdfReader, outline_items: list[Any]) -> list[Any]:
    """Serialize the raw pypdf outline tree into JSON-safe nested data."""

    serialized: list[Any] = []
    for item in outline_items:
        if isinstance(item, list):
            serialized.append(serialize_pypdf_outline(reader, item))
            continue
        title = _normalize_title(getattr(item, "title", str(item)))
        try:
            page_index = reader.get_destination_page_number(item)
        except Exception:  # pragma: no cover - defensive against odd outline objects
            page_index = None
        serialized.append(
            {
                "kind": type(item).__name__,
                "title": title,
                "page_index": page_index,
            },
        )
    return serialized


def extract_pypdf_outlines(reader: PdfReader) -> tuple[list[Any], list[OutlineEntry]]:
    """Return raw and normalized outline representations from pypdf."""

    outline_items = list(reader.outline)
    raw_outline = serialize_pypdf_outline(reader, outline_items)
    normalized: list[OutlineEntry] = []

    def walk(items: Iterable[Any], level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            title = _normalize_title(getattr(item, "title", str(item)))
            try:
                page_index = reader.get_destination_page_number(item)
            except Exception:  # pragma: no cover - defensive against odd outline objects
                page_index = None
            normalized.append(
                OutlineEntry(
                    level=level,
                    title=title,
                    page_index=page_index,
                    source=OutlineSource.PYPDF,
                ),
            )

    walk(outline_items, 1)
    return raw_outline, normalized


def score_outline(entries: list[OutlineEntry], source: OutlineSource) -> OutlineQualityReport:
    """Compute a deterministic quality report for a normalized outline."""

    if not entries:
        return OutlineQualityReport(
            source=source,
            entry_count=0,
            null_destination_count=0,
            empty_title_count=0,
            non_monotonic_count=0,
            invalid_level_count=0,
            max_depth=0,
            score=0,
        )

    null_destination_count = sum(1 for entry in entries if entry.page_index is None)
    empty_title_count = sum(1 for entry in entries if not entry.title)

    previous_page_index: int | None = None
    non_monotonic_count = 0
    for entry in entries:
        if entry.page_index is None:
            continue
        if previous_page_index is not None and entry.page_index < previous_page_index:
            non_monotonic_count += 1
        previous_page_index = entry.page_index

    invalid_level_count = 0
    previous_level = 0
    max_depth = 0
    for index, entry in enumerate(entries):
        if entry.level < 1:
            invalid_level_count += 1
        if index == 0:
            if entry.level != 1:
                invalid_level_count += 1
        elif entry.level > previous_level + 1:
            invalid_level_count += 1
        previous_level = entry.level
        max_depth = max(max_depth, entry.level)

    score = (
        len(entries) * 100
        - null_destination_count * 40
        - empty_title_count * 25
        - non_monotonic_count * 30
        - invalid_level_count * 50
        - max(0, max_depth - 12) * 5
    )

    return OutlineQualityReport(
        source=source,
        entry_count=len(entries),
        null_destination_count=null_destination_count,
        empty_title_count=empty_title_count,
        non_monotonic_count=non_monotonic_count,
        invalid_level_count=invalid_level_count,
        max_depth=max_depth,
        score=score,
    )


def select_outline(
    pymupdf_entries: list[OutlineEntry],
    pypdf_entries: list[OutlineEntry],
) -> tuple[OutlineSource, list[OutlineEntry], tuple[OutlineQualityReport, ...]]:
    """Pick the best normalized outline according to deterministic quality metrics."""

    pymupdf_report = score_outline(pymupdf_entries, OutlineSource.PYMUPDF)
    pypdf_report = score_outline(pypdf_entries, OutlineSource.PYPDF)
    reports = (pymupdf_report, pypdf_report)

    if pymupdf_report.score > pypdf_report.score:
        return OutlineSource.PYMUPDF, pymupdf_entries, reports
    if pypdf_report.score > pymupdf_report.score:
        return OutlineSource.PYPDF, pypdf_entries, reports
    if pymupdf_report.null_destination_count < pypdf_report.null_destination_count:
        return OutlineSource.PYMUPDF, pymupdf_entries, reports
    if pypdf_report.null_destination_count < pymupdf_report.null_destination_count:
        return OutlineSource.PYPDF, pypdf_entries, reports
    if pymupdf_entries:
        return OutlineSource.PYMUPDF, pymupdf_entries, reports
    if pypdf_entries:
        return OutlineSource.PYPDF, pypdf_entries, reports
    return OutlineSource.NONE, [], reports
