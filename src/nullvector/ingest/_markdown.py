"""Deterministic helpers for Markdown-native acquisition."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from nullvector.domain.ledger import MarkdownAcquisitionSettings, OutlineEntry, OutlineSource
from nullvector.ingest.errors import InvalidSourceError

_ATX_HEADING_PATTERN = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>.+?)(?:[ \t]+#+[ \t]*)?$")
_THEMATIC_BREAK_PATTERN = re.compile(r"^(?:\s*)([*_-])(?:\s*\1){2,}\s*$")
_LINE_HEIGHT = 14.0


@dataclass(frozen=True)
class MarkdownLine:
    """Normalized Markdown line retained in the canonical ledger."""

    content: str
    heading_level: int | None = None


@dataclass(frozen=True)
class MarkdownLogicalPage:
    """Logical page emitted from deterministic Markdown pagination."""

    page_index: int
    lines: tuple[MarkdownLine, ...]


@dataclass(frozen=True)
class ParsedMarkdownDocument:
    """Parsed Markdown document with logical pages and synthetic outline."""

    pages: tuple[MarkdownLogicalPage, ...]
    outline_entries: tuple[OutlineEntry, ...]


@dataclass(frozen=True)
class _MarkdownUnit:
    lines: tuple[MarkdownLine, ...]
    atomic: bool = False
    page_break_before: bool = False


def normalize_markdown_text(raw_text: str) -> str:
    """Normalize source newlines to ``\\n`` for deterministic parsing."""

    return raw_text.replace("\r\n", "\n").replace("\r", "\n")


def read_markdown_text(source_path: str) -> str:
    """Read authored Markdown from disk as UTF-8 text."""

    source = Path(source_path)
    if not source.exists():
        raise InvalidSourceError("source markdown does not exist", source_path=str(source))
    if not source.is_file():
        raise InvalidSourceError("source path must be a file", source_path=str(source))

    try:
        raw_text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidSourceError(
            "source markdown must be UTF-8 encoded",
            source_path=str(source.resolve()),
        ) from exc
    return normalize_markdown_text(raw_text)


def count_markdown_logical_pages(
    source_path: str,
    settings: MarkdownAcquisitionSettings,
) -> int:
    """Return the logical-page count for a Markdown source."""

    return len(parse_markdown_source(source_path, settings=settings).pages)


def parse_markdown_source(
    source_path: str,
    *,
    settings: MarkdownAcquisitionSettings,
) -> ParsedMarkdownDocument:
    """Parse authored Markdown into logical pages and a synthetic outline."""

    text = read_markdown_text(source_path)
    units = _parse_units(text, settings=settings)
    pages = _paginate_units(units, settings=settings)
    outline_entries: list[OutlineEntry] = []
    for page in pages:
        for line in page.lines:
            if line.heading_level is None:
                continue
            outline_entries.append(
                OutlineEntry(
                    level=line.heading_level,
                    title=line.content,
                    page_index=page.page_index,
                    source=OutlineSource.MARKDOWN,
                )
            )
    return ParsedMarkdownDocument(pages=pages, outline_entries=tuple(outline_entries))


def synthetic_line_top_y(reading_index: int) -> float:
    """Return the synthetic line top position for a logical page."""

    return float(reading_index) * _LINE_HEIGHT


def synthetic_heading_font_size(level: int | None) -> float:
    """Return a deterministic heading/body font size for logical layout cues."""

    if level is None:
        return 12.0
    return float(max(13, 24 - (level - 1) * 2))


def _normalize_heading_title(line: str) -> tuple[int, str] | None:
    match = _ATX_HEADING_PATTERN.match(line.strip())
    if match is None:
        return None
    title = match.group("title").strip()
    if not title:
        return None
    return (len(match.group("marks")), title)


def _is_thematic_break(line: str) -> bool:
    return _THEMATIC_BREAK_PATTERN.match(line) is not None


def _fence_open(line: str) -> tuple[str, int] | None:
    stripped = line.lstrip()
    if not stripped:
        return None
    first = stripped[0]
    if first not in {"`", "~"}:
        return None
    count = 0
    for char in stripped:
        if char != first:
            break
        count += 1
    if count < 3:
        return None
    return (first, count)


def _is_fence_close(line: str, fence_char: str, fence_length: int) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if any(char != fence_char for char in stripped):
        return False
    return len(stripped) >= fence_length


def _parse_units(
    text: str,
    *,
    settings: MarkdownAcquisitionSettings,
) -> tuple[_MarkdownUnit, ...]:
    raw_lines = text.split("\n")
    units: list[_MarkdownUnit] = []
    fenced_lines: list[MarkdownLine] = []
    active_fence: tuple[str, int] | None = None
    pending_page_break = False

    for raw_line in raw_lines:
        line = raw_line.rstrip()

        if active_fence is not None:
            if _is_fence_close(line, active_fence[0], active_fence[1]):
                units.append(
                    _MarkdownUnit(
                        lines=tuple(fenced_lines),
                        atomic=True,
                        page_break_before=pending_page_break,
                    )
                )
                fenced_lines = []
                active_fence = None
                pending_page_break = False
                continue
            if line:
                fenced_lines.append(MarkdownLine(content=line))
            continue

        fence = _fence_open(line)
        if fence is not None:
            fenced_lines = [MarkdownLine(content=line)] if line else []
            active_fence = fence
            continue

        if not line.strip():
            continue

        if settings.split_on_thematic_breaks and _is_thematic_break(line):
            pending_page_break = True
            continue

        heading = _normalize_heading_title(line)
        if heading is not None:
            level, title = heading
            units.append(
                _MarkdownUnit(
                    lines=(MarkdownLine(content=title, heading_level=level),),
                    page_break_before=pending_page_break,
                )
            )
            pending_page_break = False
            continue

        units.append(
            _MarkdownUnit(
                lines=(MarkdownLine(content=line),),
                page_break_before=pending_page_break,
            )
        )
        pending_page_break = False

    if fenced_lines:
        units.append(
            _MarkdownUnit(
                lines=tuple(fenced_lines),
                atomic=True,
                page_break_before=pending_page_break,
            )
        )

    return tuple(units)


def _paginate_units(
    units: tuple[_MarkdownUnit, ...],
    *,
    settings: MarkdownAcquisitionSettings,
) -> tuple[MarkdownLogicalPage, ...]:
    pages: list[MarkdownLogicalPage] = []
    current_lines: list[MarkdownLine] = []
    max_lines = settings.max_logical_lines_per_page

    def flush_page() -> None:
        nonlocal current_lines
        if not current_lines:
            return
        pages.append(
            MarkdownLogicalPage(
                page_index=len(pages),
                lines=tuple(current_lines),
            )
        )
        current_lines = []

    def append_line(line: MarkdownLine) -> None:
        if len(current_lines) >= max_lines:
            flush_page()
        current_lines.append(line)

    for unit in units:
        if unit.page_break_before:
            flush_page()

        if unit.atomic:
            if current_lines and len(current_lines) + len(unit.lines) > max_lines:
                flush_page()
            if len(unit.lines) <= max_lines:
                current_lines.extend(unit.lines)
                continue
            for line in unit.lines:
                append_line(line)
            continue

        for line in unit.lines:
            append_line(line)

    flush_page()
    return tuple(pages)
