"""Deterministic heading extraction and scoring over persisted Phase 01 artifacts."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from nullvector._text import (
    casefold_punct_key as shared_casefold_punct_key,
)
from nullvector._text import (
    collapse_whitespace as shared_collapse_whitespace,
)
from nullvector._text import (
    display_text,
    levenshtein_distance,
    normalized_text_key,
)
from nullvector.domain.ledger import CanonicalTextLine, OutlineEntry
from nullvector.domain.tree import (
    AnchorSource,
    HeadingCandidate,
    HeadingScoreBreakdown,
    HeadingSourceKind,
    NodeAnchor,
    OutlineAnchorRecord,
    OutlineAnchorStatus,
    TreeSettings,
)
from nullvector.tree._constants import (
    MAXIMUM_ALLOWED_PAGE_ADJACENCY,
    REPEATED_HEADER_FOOTER_MIN_REPETITIONS,
    SHORT_TITLE_EDIT_DISTANCE_THRESHOLD,
    SHORT_TITLE_MAX_LENGTH_FOR_EDIT_DISTANCE,
    TITLE_TOKEN_CONTAINMENT_THRESHOLD,
)

NUMBERING_PATTERN = re.compile(r"^(?P<prefix>\d+(?:\.\d+)*)(?:[.)])?\s+(?P<title>.+)$")


@dataclass(frozen=True)
class PageArtifacts:
    """Minimal Phase 01 page substrate consumed by Phase 02 logic."""

    page_index: int
    text: str
    rawdict: dict[str, Any] | None
    page_label: str | None = None
    canonical_lines: tuple[CanonicalTextLine, ...] = ()


@dataclass(frozen=True)
class PageLine:
    """Ordered page-local line span with stable occurrence indexing."""

    page_index: int
    text: str
    normalized_text: str
    casefold_punct_text: str
    start_offset: int
    end_offset: int
    occurrence_index: int
    anchor_source: AnchorSource
    top_y: float | None = None
    font_size: float | None = None


def collapse_whitespace(value: str) -> str:
    """Collapse internal whitespace while preserving character meaning."""

    return shared_collapse_whitespace(value)


def strip_line_preserve_internal_whitespace(value: str) -> str:
    """Trim a line without collapsing internal whitespace."""

    return value.strip()


def normalize_heading_text(value: str) -> str:
    """Return a display-stable heading string with collapsed whitespace."""

    return display_text(value)


def normalized_title_key(value: str) -> str:
    """Return a casefolded comparison key for title matching and path stability."""

    return normalized_text_key(value)


def casefold_punct_key(value: str) -> str:
    """Return a punctuation-insensitive comparison key."""

    return shared_casefold_punct_key(value)


def tokenize_title(value: str) -> tuple[str, ...]:
    """Extract alphanumeric tokens from a title-like string."""

    normalized = casefold_punct_key(value)
    return tuple(token for token in normalized.split() if token)


def _levenshtein_distance(left: str, right: str) -> int:
    return levenshtein_distance(left, right)


def numbering_depth(value: str) -> int | None:
    """Infer heading depth from a leading dotted numbering prefix."""

    match = NUMBERING_PATTERN.match(normalize_heading_text(value))
    if match is None:
        return None
    return len(match.group("prefix").split("."))


def split_text_lines_with_offsets(text: str, page_index: int) -> list[PageLine]:
    """Split page text into ordered line spans with deterministic occurrence indexes."""

    lines: list[PageLine] = []
    occurrence_counts: dict[str, int] = defaultdict(int)
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_text = raw_line.rstrip("\r\n")
        leading_trim = len(line_text) - len(line_text.lstrip())
        trailing_trim = len(line_text) - len(line_text.rstrip())
        literal_text = line_text[leading_trim : len(line_text) - trailing_trim or None]
        start_offset = offset + leading_trim
        end_offset = start_offset + len(literal_text)
        offset += len(raw_line)
        if not literal_text.strip():
            continue
        normalized = normalized_title_key(literal_text)
        occurrence_index = occurrence_counts[normalized]
        occurrence_counts[normalized] += 1
        lines.append(
            PageLine(
                page_index=page_index,
                text=literal_text,
                normalized_text=normalized,
                casefold_punct_text=casefold_punct_key(literal_text),
                start_offset=start_offset,
                end_offset=end_offset,
                occurrence_index=occurrence_index,
                anchor_source=AnchorSource.TEXT,
            ),
        )
    return lines


def _chars_text(chars: list[dict[str, Any]]) -> str:
    return "".join(str(char.get("c", "")) for char in chars)


def _line_text_from_rawdict(line: dict[str, Any]) -> str:
    spans = line.get("spans", [])
    pieces: list[str] = []
    for span in spans:
        chars = span.get("chars")
        if isinstance(chars, list) and chars:
            pieces.append(_chars_text(chars))
            continue
        text = span.get("text")
        if isinstance(text, str):
            pieces.append(text)
    return strip_line_preserve_internal_whitespace("".join(pieces))


def extract_rawdict_lines(
    rawdict: dict[str, Any] | None,
    page_index: int,
    text_lines: list[PageLine],
) -> list[PageLine]:
    """Extract ordered rawdict lines and map them to the same nth text occurrence."""

    if rawdict is None:
        return []

    text_occurrences: dict[str, list[PageLine]] = defaultdict(list)
    for line in text_lines:
        text_occurrences[line.normalized_text].append(line)

    rawdict_lines: list[PageLine] = []
    rawdict_counts: dict[str, int] = defaultdict(int)
    blocks = rawdict.get("blocks", [])
    for block in blocks:
        if not isinstance(block, dict):
            continue
        lines = block.get("lines", [])
        for line in lines:
            if not isinstance(line, dict):
                continue
            text = _line_text_from_rawdict(line)
            if not text:
                continue
            normalized = normalized_title_key(text)
            occurrence_index = rawdict_counts[normalized]
            rawdict_counts[normalized] += 1
            matched_lines = text_occurrences.get(normalized)
            if not matched_lines or occurrence_index >= len(matched_lines):
                continue
            matched_line = matched_lines[occurrence_index]
            font_sizes = [
                float(span["size"])
                for span in line.get("spans", [])
                if isinstance(span, dict) and isinstance(span.get("size"), int | float)
            ]
            bbox = line.get("bbox")
            top_y = float(bbox[1]) if isinstance(bbox, list) and len(bbox) >= 2 else None
            rawdict_lines.append(
                PageLine(
                    page_index=page_index,
                    text=matched_line.text,
                    normalized_text=matched_line.normalized_text,
                    casefold_punct_text=matched_line.casefold_punct_text,
                    start_offset=matched_line.start_offset,
                    end_offset=matched_line.end_offset,
                    occurrence_index=occurrence_index,
                    anchor_source=AnchorSource.RAWDICT,
                    top_y=top_y,
                    font_size=max(font_sizes) if font_sizes else None,
                ),
            )
    return rawdict_lines


def find_repeated_header_footer_lines(
    pages: tuple[PageArtifacts, ...],
    settings: TreeSettings,
) -> set[str]:
    """Detect repeated header/footer strings using first/last non-empty lines per page."""

    repeated_candidates: Counter[str] = Counter()
    for page in pages:
        text_lines = split_text_lines_with_offsets(page.text, page.page_index)
        if not text_lines:
            continue
        repeated_candidates[text_lines[0].normalized_text] += 1
        if len(text_lines) > 1:
            repeated_candidates[text_lines[-1].normalized_text] += 1

    return {
        line
        for line, count in repeated_candidates.items()
        if count >= REPEATED_HEADER_FOOTER_MIN_REPETITIONS
    }


def build_node_anchor(line: PageLine) -> NodeAnchor:
    """Project a page-local line span into a typed node anchor."""

    return NodeAnchor(
        page=line.page_index,
        start_offset=line.start_offset,
        end_offset=line.end_offset,
        anchor_text=line.text,
        anchor_source=line.anchor_source,
        occurrence_index=line.occurrence_index,
    )


def _line_lists_for_page(page: PageArtifacts) -> tuple[list[PageLine], list[PageLine]]:
    if page.canonical_lines:
        text_lines = [
            PageLine(
                page_index=line.page_index,
                text=line.content,
                normalized_text=line.normalized_text,
                casefold_punct_text=line.casefold_punct_text,
                start_offset=line.start_offset,
                end_offset=line.end_offset,
                occurrence_index=line.occurrence_index,
                anchor_source=AnchorSource.TEXT,
                top_y=line.top_y,
                font_size=line.font_size,
            )
            for line in sorted(
                page.canonical_lines,
                key=lambda item: (item.reading_index, item.occurrence_index, item.line_id),
            )
        ]
        rawdict_lines = [
            PageLine(
                page_index=line.page_index,
                text=line.text,
                normalized_text=line.normalized_text,
                casefold_punct_text=line.casefold_punct_text,
                start_offset=line.start_offset,
                end_offset=line.end_offset,
                occurrence_index=line.occurrence_index,
                anchor_source=AnchorSource.RAWDICT,
                top_y=line.top_y,
                font_size=line.font_size,
            )
            for line in text_lines
            if line.font_size is not None or line.top_y is not None
        ]
        return text_lines, rawdict_lines

    text_lines = split_text_lines_with_offsets(page.text, page.page_index)
    rawdict_lines = extract_rawdict_lines(page.rawdict, page.page_index, text_lines)
    return text_lines, rawdict_lines


def anchor_title_on_page(
    title: str,
    page: PageArtifacts,
    *,
    occurrence_index: int = 0,
    settings: TreeSettings | None = None,
) -> NodeAnchor | None:
    """Anchor a title to the nth matching page line, preferring rawdict-backed grouping."""

    normalized = normalized_title_key(title)
    punct_key = casefold_punct_key(title)
    title_tokens = set(tokenize_title(title))
    text_lines, rawdict_lines = _line_lists_for_page(page)

    for candidate_lines in (rawdict_lines, text_lines):
        exact = [line for line in candidate_lines if line.normalized_text == normalized]
        if occurrence_index < len(exact):
            return build_node_anchor(exact[occurrence_index])
        punct = [line for line in candidate_lines if line.casefold_punct_text == punct_key]
        if occurrence_index < len(punct):
            return build_node_anchor(punct[occurrence_index])
        if settings is None:
            continue
        if title_tokens:
            containment = [
                line
                for line in candidate_lines
                if (line_tokens := set(tokenize_title(line.text)))
                and len(title_tokens & line_tokens) / len(title_tokens)
                >= TITLE_TOKEN_CONTAINMENT_THRESHOLD
            ]
            if occurrence_index < len(containment):
                return build_node_anchor(containment[occurrence_index])
        if len(normalized) <= SHORT_TITLE_MAX_LENGTH_FOR_EDIT_DISTANCE:
            edit_matches = [
                line
                for line in candidate_lines
                if _levenshtein_distance(normalized, line.normalized_text)
                <= SHORT_TITLE_EDIT_DISTANCE_THRESHOLD
            ]
            if occurrence_index < len(edit_matches):
                return build_node_anchor(edit_matches[occurrence_index])
    return None


def _is_title_case_heading(value: str) -> bool:
    words = [word for word in value.split() if word]
    if not words:
        return False
    return all(word[:1].isupper() for word in words if any(char.isalpha() for char in word))


def _is_uppercase_heading(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    return bool(letters) and all(char.isupper() for char in letters)


def _matches_outline_title(
    line: PageLine,
    outline_entries: tuple[OutlineEntry, ...],
    settings: TreeSettings,
) -> tuple[bool, int | None]:
    for entry in outline_entries:
        if entry.page_index is None:
            continue
        if abs(entry.page_index - line.page_index) > MAXIMUM_ALLOWED_PAGE_ADJACENCY:
            continue
        if normalized_title_key(entry.title) == line.normalized_text:
            return True, entry.level
    return False, None


def score_heading_line(
    line: PageLine,
    *,
    page_line_count: int,
    repeated_lines: set[str],
    outline_entries: tuple[OutlineEntry, ...],
    settings: TreeSettings,
) -> tuple[HeadingScoreBreakdown, int | None]:
    """Score a candidate heading line using explicit deterministic signals."""

    word_count = len(line.text.split())
    numbering_signal = (
        settings.heading_numbering_signal if numbering_depth(line.text) is not None else 0
    )
    isolation_signal = (
        settings.heading_sparse_page_isolation_signal
        if page_line_count <= settings.heading_sparse_page_line_count
        else settings.heading_first_occurrence_isolation_signal
        if line.occurrence_index == 0
        else 0
    )
    short_line_signal = (
        settings.heading_short_line_signal
        if 1 <= word_count <= settings.heading_short_line_max_words
        else settings.heading_medium_line_signal
        if word_count <= settings.heading_medium_line_max_words
        else 0
    )
    title_case_signal = (
        settings.heading_title_case_signal if _is_title_case_heading(line.text) else 0
    )
    uppercase_signal = (
        settings.heading_uppercase_signal
        if _is_uppercase_heading(line.text) and word_count <= settings.heading_uppercase_max_words
        else 0
    )
    punctuation_penalty = (
        -settings.heading_punctuation_penalty
        if line.text.endswith((".", ",", ";", "?", "!"))
        else 0
    )
    if line.normalized_text.startswith(("figure ", "table ", "appendix marker ")):
        punctuation_penalty -= settings.heading_figure_like_penalty
    repeated_header_footer_penalty = (
        -settings.heading_repeated_header_footer_penalty
        if line.normalized_text in repeated_lines
        else 0
    )
    toc_overlap, outline_level_hint = _matches_outline_title(line, outline_entries, settings)
    toc_overlap_signal = settings.heading_toc_overlap_signal if toc_overlap else 0
    layout_cues_available = line.anchor_source == AnchorSource.RAWDICT
    layout_signal = 0
    if layout_cues_available and (
        (line.top_y is not None and line.top_y <= settings.heading_top_margin_threshold)
        or (line.font_size is not None and line.font_size >= settings.heading_min_font_size)
    ):
        layout_signal = settings.heading_layout_signal

    final_score = (
        numbering_signal
        + isolation_signal
        + short_line_signal
        + title_case_signal
        + uppercase_signal
        + punctuation_penalty
        + repeated_header_footer_penalty
        + toc_overlap_signal
        + layout_signal
    )
    return (
        HeadingScoreBreakdown(
            numbering_signal=numbering_signal,
            isolation_signal=isolation_signal,
            short_line_signal=short_line_signal,
            title_case_signal=title_case_signal,
            uppercase_signal=uppercase_signal,
            punctuation_penalty=punctuation_penalty,
            repeated_header_footer_penalty=repeated_header_footer_penalty,
            toc_overlap_signal=toc_overlap_signal,
            layout_signal=layout_signal,
            layout_cues_available=layout_cues_available,
            final_score=final_score,
        ),
        outline_level_hint,
    )


def extract_outline_candidates(
    document_id: str,
    pages: tuple[PageArtifacts, ...],
    outline_entries: tuple[OutlineEntry, ...],
    settings: TreeSettings | None = None,
) -> tuple[HeadingCandidate, ...]:
    """Project selected outline entries into anchored high-confidence heading candidates."""

    pages_by_index = {page.page_index: page for page in pages}
    candidates: list[HeadingCandidate] = []
    occurrence_counts: dict[tuple[int, str], int] = defaultdict(int)
    for entry in outline_entries:
        if entry.page_index is None:
            continue
        page = pages_by_index.get(entry.page_index)
        if page is None:
            continue
        normalized_title = normalized_title_key(entry.title)
        occurrence_key = (entry.page_index, normalized_title)
        occurrence_index = occurrence_counts[occurrence_key]
        occurrence_counts[occurrence_key] += 1
        anchor = anchor_title_on_page(
            entry.title,
            page,
            occurrence_index=occurrence_index,
            settings=settings,
        )
        if anchor is None:
            continue
        candidates.append(
            HeadingCandidate(
                document_id=document_id,
                page_index=entry.page_index,
                title=normalize_heading_text(entry.title),
                normalized_title=normalized_title,
                anchor=anchor,
                source_kind=HeadingSourceKind.OUTLINE,
                level_hint=entry.level,
                outline_level_hint=entry.level,
                score_breakdown=HeadingScoreBreakdown(
                    toc_overlap_signal=40,
                    final_score=100,
                ),
                keep=True,
                high_confidence=True,
            ),
        )
    return tuple(candidates)


def extract_outline_candidates_with_records(
    document_id: str,
    pages: tuple[PageArtifacts, ...],
    outline_entries: tuple[OutlineEntry, ...],
    settings: TreeSettings | None = None,
) -> tuple[tuple[HeadingCandidate, ...], tuple[OutlineAnchorRecord, ...]]:
    """Project outline entries into anchored candidates plus explicit anchoring outcomes."""

    pages_by_index = {page.page_index: page for page in pages}
    candidates: list[HeadingCandidate] = []
    records: list[OutlineAnchorRecord] = []
    occurrence_counts: dict[tuple[int, str], int] = defaultdict(int)
    for entry in outline_entries:
        normalized_title = normalized_title_key(entry.title)
        if entry.page_index is None:
            records.append(
                OutlineAnchorRecord(
                    document_id=document_id,
                    title=normalize_heading_text(entry.title),
                    normalized_title=normalized_title,
                    page_index=None,
                    source=entry.source.value,
                    status=OutlineAnchorStatus.REJECTED,
                    reason="outline_entry_has_no_page_index",
                )
            )
            continue
        page = pages_by_index.get(entry.page_index)
        if page is None:
            records.append(
                OutlineAnchorRecord(
                    document_id=document_id,
                    title=normalize_heading_text(entry.title),
                    normalized_title=normalized_title,
                    page_index=entry.page_index,
                    source=entry.source.value,
                    status=OutlineAnchorStatus.REJECTED,
                    reason="heading_page_artifact_missing",
                )
            )
            continue
        occurrence_key = (entry.page_index, normalized_title)
        occurrence_index = occurrence_counts[occurrence_key]
        occurrence_counts[occurrence_key] += 1
        anchor = anchor_title_on_page(
            entry.title,
            page,
            occurrence_index=occurrence_index,
            settings=settings,
        )
        if anchor is None:
            records.append(
                OutlineAnchorRecord(
                    document_id=document_id,
                    title=normalize_heading_text(entry.title),
                    normalized_title=normalized_title,
                    page_index=entry.page_index,
                    source=entry.source.value,
                    status=OutlineAnchorStatus.OUTLINE_KNOWN_BUT_UNANCHORED,
                    reason="page_present_but_title_not_visible",
                )
            )
            continue
        candidate = HeadingCandidate(
            document_id=document_id,
            page_index=entry.page_index,
            title=normalize_heading_text(entry.title),
            normalized_title=normalized_title,
            anchor=anchor,
            source_kind=HeadingSourceKind.OUTLINE,
            level_hint=entry.level,
            outline_level_hint=entry.level,
            score_breakdown=HeadingScoreBreakdown(
                toc_overlap_signal=40,
                final_score=100,
            ),
            keep=True,
            high_confidence=True,
        )
        candidates.append(candidate)
        records.append(
            OutlineAnchorRecord(
                document_id=document_id,
                title=candidate.title,
                normalized_title=candidate.normalized_title,
                page_index=entry.page_index,
                source=entry.source.value,
                status=OutlineAnchorStatus.ANCHORED_TO_PHYSICAL_TEXT,
                anchor=anchor,
            )
        )
    return tuple(candidates), tuple(records)


def extract_inferred_candidates(
    document_id: str,
    pages: tuple[PageArtifacts, ...],
    outline_entries: tuple[OutlineEntry, ...],
    settings: TreeSettings,
) -> tuple[HeadingCandidate, ...]:
    """Extract scored heading candidates from persisted page text and sampled rawdict."""

    repeated_lines = find_repeated_header_footer_lines(pages, settings)
    outline_tuple = tuple(outline_entries)
    candidates: list[HeadingCandidate] = []

    for page in pages:
        text_lines, rawdict_lines = _line_lists_for_page(page)
        rawdict_lookup = {
            (line.normalized_text, line.occurrence_index): line for line in rawdict_lines
        }
        for text_line in text_lines:
            line = rawdict_lookup.get(
                (text_line.normalized_text, text_line.occurrence_index), text_line
            )
            score_breakdown, outline_level_hint = score_heading_line(
                line,
                page_line_count=len(text_lines),
                repeated_lines=repeated_lines,
                outline_entries=outline_tuple,
                settings=settings,
            )
            final_score = score_breakdown.final_score
            keep = final_score >= settings.heading_score_keep_threshold
            high_confidence = final_score >= settings.heading_score_high_confidence_threshold
            candidates.append(
                HeadingCandidate(
                    document_id=document_id,
                    page_index=page.page_index,
                    title=line.text,
                    normalized_title=line.normalized_text,
                    anchor=build_node_anchor(line),
                    source_kind=(
                        HeadingSourceKind.RAWDICT
                        if line.anchor_source == AnchorSource.RAWDICT
                        else HeadingSourceKind.TEXT
                    ),
                    level_hint=numbering_depth(line.text),
                    outline_level_hint=outline_level_hint,
                    score_breakdown=score_breakdown,
                    keep=keep,
                    high_confidence=high_confidence,
                ),
            )

    return tuple(candidates)


def extract_heading_candidates(
    document_id: str,
    pages: tuple[PageArtifacts, ...],
    outline_entries: tuple[OutlineEntry, ...],
    settings: TreeSettings,
) -> tuple[tuple[HeadingCandidate, ...], tuple[HeadingCandidate, ...]]:
    """Return both outline-derived and inferred heading candidates."""

    return (
        extract_outline_candidates(document_id, pages, outline_entries, settings=settings),
        extract_inferred_candidates(document_id, pages, outline_entries, settings),
    )
