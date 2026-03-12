"""Deterministic TOC parsing and physical-page reconciliation."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from strataforge.domain.models import (
    HeadingCandidate,
    HeadingScoreBreakdown,
    HeadingSourceKind,
    TocDetectionResult,
    TocParsedEntry,
    TocParseMethod,
    TocParseResponse,
    TocReconciliationResult,
    TreeSettings,
)
from strataforge.llm.prompts import build_toc_parse_messages
from strataforge.llm.protocols import StructuredLLMGateway
from strataforge.llm.types import GatewayRequest
from strataforge.tree.headings import (
    PageArtifacts,
    anchor_title_on_page,
    normalized_title_key,
    numbering_depth,
)

CHAPTER_STRUCTURE_PATTERN = re.compile(r"^(chapter\s+\d+)(?::|\.)?\s+(?P<title>.+)$", re.IGNORECASE)
NUMBERED_WITH_PAGE_PATTERN = re.compile(
    r"^(?P<structure>\d+(?:\.\d+){0,5}[.)]?)\s+(?P<title>.+?)\s*(?:\.{2,}\s*|\s{2,})(?P<page>\d{1,4})$"
)
NUMBERED_SIMPLE_PATTERN = re.compile(
    r"^(?P<structure>\d+(?:\.\d+){0,5}[.)]?)\s+(?P<title>.+?)\s+(?P<page>\d{1,4})$"
)
CHAPTER_WITH_PAGE_PATTERN = re.compile(
    r"^(?P<structure>chapter\s+\d+)(?::|\.)?\s+(?P<title>.+?)\s*(?:\.{2,}\s*|\s{2,})(?P<page>\d{1,4})$",
    re.IGNORECASE,
)
TITLE_WITH_PAGE_PATTERN = re.compile(r"^(?P<title>.+?)\s*(?:\.{2,}\s*|\s{2,})(?P<page>\d{1,4})$")
TITLE_HEADING_PATTERN = re.compile(r"^(?P<title>[A-Za-z][^\d]{2,})$")


def _json_safe(value: object) -> object:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    return str(path)


def _clean_title(value: str) -> str:
    return " ".join(value.split()).strip(" .")


def _parse_toc_line(line: str) -> TocParsedEntry | None:
    stripped = line.strip()
    if not stripped or normalized_title_key(stripped) in {"table of contents", "contents"}:
        return None

    for pattern in (
        CHAPTER_WITH_PAGE_PATTERN,
        NUMBERED_WITH_PAGE_PATTERN,
        NUMBERED_SIMPLE_PATTERN,
        TITLE_WITH_PAGE_PATTERN,
    ):
        match = pattern.match(stripped)
        if match is None:
            continue
        structure = match.groupdict().get("structure")
        title = _clean_title(match.group("title"))
        page_value = match.groupdict().get("page")
        return TocParsedEntry(
            structure=structure,
            title=title,
            page_number=int(page_value) if page_value is not None else None,
        )

    chapter_match = CHAPTER_STRUCTURE_PATTERN.match(stripped)
    if chapter_match is not None:
        return TocParsedEntry(
            structure=chapter_match.group(1),
            title=_clean_title(chapter_match.group("title")),
        )

    title_only = TITLE_HEADING_PATTERN.match(stripped)
    if title_only is not None:
        return TocParsedEntry(title=_clean_title(title_only.group("title")))

    return None


def deterministic_parse_toc_text(toc_text: str) -> tuple[TocParsedEntry, ...]:
    """Parse TOC text with bounded regex-first deterministic logic."""

    entries: list[TocParsedEntry] = []
    for raw_line in toc_text.splitlines():
        entry = _parse_toc_line(raw_line)
        if entry is not None:
            entries.append(entry)
    return tuple(entries)


def is_materially_useful(entries: tuple[TocParsedEntry, ...]) -> bool:
    """Return whether deterministic TOC parsing is strong enough to trust."""

    numbered_count = sum(1 for entry in entries if entry.page_number is not None)
    return numbered_count >= 3 or len(entries) >= 5


def infer_structure_depth(entry: TocParsedEntry) -> int | None:
    """Infer a depth hint from structure prefixes."""

    if entry.structure is None:
        return numbering_depth(entry.title)
    structure = entry.structure.strip()
    numbered = numbering_depth(structure)
    if numbered is not None:
        return numbered
    if structure.casefold().startswith("chapter "):
        return 1
    return numbering_depth(entry.title)


def _pair_search_window(
    *,
    toc_result: TocDetectionResult,
    total_pages: int,
) -> tuple[int, int]:
    if not toc_result.toc_page_indices:
        return 0, max(total_pages - 1, 0)
    last_toc_page = toc_result.toc_page_indices[-1]
    start = min(last_toc_page + 1, max(total_pages - 1, 0))
    end = min(last_toc_page + 80, max(total_pages - 1, 0))
    return start, end


def collect_anchor_pairs(
    *,
    pages: tuple[PageArtifacts, ...],
    toc_result: TocDetectionResult,
    parsed_entries: tuple[TocParsedEntry, ...],
) -> tuple[tuple[int, int], ...]:
    """Collect bounded logical-to-physical page anchor pairs."""

    if not parsed_entries:
        return ()

    start_page, end_page = _pair_search_window(toc_result=toc_result, total_pages=len(pages))
    pages_by_index = {page.page_index: page for page in pages}
    pairs: list[tuple[int, int]] = []

    for entry in [item for item in parsed_entries if item.page_number is not None][:10]:
        for page_index in range(start_page, end_page + 1):
            page = pages_by_index.get(page_index)
            if page is None:
                continue
            if anchor_title_on_page(entry.title, page) is not None:
                pairs.append((entry.page_number or 0, page_index))
                break
    return tuple(pairs)


def mode_offset_from_pairs(pairs: tuple[tuple[int, int], ...]) -> tuple[int | None, float]:
    """Return the mode page offset and its agreement confidence."""

    if not pairs:
        return None, 0.0
    offsets = [physical - logical for logical, physical in pairs]
    offset_counter = Counter(offsets)
    offset, agreeing_pairs = offset_counter.most_common(1)[0]
    return offset, agreeing_pairs / len(pairs)


def toc_entry_to_candidate(
    *,
    document_id: str,
    entry: TocParsedEntry,
    page_index: int,
    pages_by_index: dict[int, PageArtifacts],
) -> HeadingCandidate | None:
    """Convert a parsed TOC entry into an anchored heading candidate."""

    page = pages_by_index.get(page_index)
    if page is None:
        return None
    anchor = anchor_title_on_page(entry.title, page)
    if anchor is None:
        return None
    depth = infer_structure_depth(entry)
    numbering_signal = 22 if depth is not None else 0
    short_line_signal = 14 if len(entry.title.split()) <= 10 else 6
    toc_overlap_signal = 40
    final_score = numbering_signal + short_line_signal + toc_overlap_signal
    return HeadingCandidate(
        document_id=document_id,
        page_index=page_index,
        title=entry.title,
        normalized_title=normalized_title_key(entry.title),
        anchor=anchor,
        source_kind=HeadingSourceKind.OUTLINE,
        level_hint=depth,
        outline_level_hint=depth,
        score_breakdown=HeadingScoreBreakdown(
            numbering_signal=numbering_signal,
            short_line_signal=short_line_signal,
            toc_overlap_signal=toc_overlap_signal,
            final_score=final_score,
        ),
        keep=True,
        high_confidence=True,
    )


def build_reconciled_candidates(
    *,
    document_id: str,
    pages: tuple[PageArtifacts, ...],
    parsed_entries: tuple[TocParsedEntry, ...],
    offset: int,
) -> tuple[HeadingCandidate, ...]:
    """Build TOC-derived candidates using a deterministic offset and bounded anchoring."""

    pages_by_index = {page.page_index: page for page in pages}
    candidates: list[HeadingCandidate] = []
    for entry in parsed_entries:
        if entry.page_number is None:
            continue
        predicted_page = entry.page_number + offset
        for page_index in (predicted_page - 1, predicted_page, predicted_page + 1):
            candidate = toc_entry_to_candidate(
                document_id=document_id,
                entry=entry,
                page_index=page_index,
                pages_by_index=pages_by_index,
            )
            if candidate is not None:
                candidates.append(candidate)
                break
    return tuple(candidates)


class TocReconciler:
    """Deterministic TOC parser with optional LLM assistance for sparse cases."""

    def __init__(
        self,
        settings: TreeSettings,
        gateway: StructuredLLMGateway | None = None,
    ) -> None:
        self._settings = settings
        self._gateway = gateway

    def reconcile(
        self,
        *,
        document_id: str,
        pages: tuple[PageArtifacts, ...],
        toc_result: TocDetectionResult,
        artifact_root: str | None = None,
    ) -> TocReconciliationResult:
        toc_text = toc_result.toc_content
        if not toc_text:
            result = TocReconciliationResult(parse_method=TocParseMethod.DETERMINISTIC)
            if artifact_root is not None:
                _write_json(Path(artifact_root) / "toc-reconciliation.json", result)
            return result

        parsed_entries = deterministic_parse_toc_text(toc_text)
        parse_method = TocParseMethod.DETERMINISTIC
        if not is_materially_useful(parsed_entries) and self._gateway is not None:
            response = self._gateway.invoke(
                GatewayRequest[TocParseResponse](
                    operation_name="toc_parse",
                    messages=build_toc_parse_messages(toc_text=toc_text),
                    response_model=TocParseResponse,
                )
            )
            parsed_entries = response.output.entries
            parse_method = TocParseMethod.LLM_ASSISTED

        pairs = collect_anchor_pairs(
            pages=pages,
            toc_result=toc_result,
            parsed_entries=parsed_entries,
        )
        offset, offset_confidence = mode_offset_from_pairs(pairs)
        reconciled_candidates: tuple[HeadingCandidate, ...] = ()
        if offset is not None:
            reconciled_candidates = build_reconciled_candidates(
                document_id=document_id,
                pages=pages,
                parsed_entries=parsed_entries,
                offset=offset,
            )

        result = TocReconciliationResult(
            parsed_entries=parsed_entries,
            offset=offset,
            offset_confidence=offset_confidence,
            reconciled_candidates=reconciled_candidates,
            parse_method=parse_method,
        )
        if artifact_root is not None:
            _write_json(Path(artifact_root) / "toc-reconciliation.json", result)
        return result
