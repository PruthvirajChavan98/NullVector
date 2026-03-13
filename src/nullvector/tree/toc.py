"""Deterministic-first TOC detection over persisted parse artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from nullvector.domain.models import (
    TocDetectionMethod,
    TocDetectionResponse,
    TocDetectionResult,
    TocPageScore,
    TreeSettings,
)
from nullvector.llm.prompts import build_toc_detection_messages
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest
from nullvector.tree.headings import (
    PageArtifacts,
    _line_lists_for_page,
    extract_rawdict_lines,
    find_repeated_header_footer_lines,
    split_text_lines_with_offsets,
)

MAX_TOC_SCAN_PAGES = 20
DETERMINISTIC_HIGH_THRESHOLD = 0.70
DETERMINISTIC_LOW_THRESHOLD = 0.45

PATTERN_MATCH_WEIGHT = 0.35
LEADER_DOT_WEIGHT = 0.20
NUMBERING_WEIGHT = 0.15
FONT_UNIFORMITY_WEIGHT = 0.10
CONSECUTIVE_PAGE_WEIGHT = 0.20
REPEATED_HEADER_PENALTY_WEIGHT = 0.25

LEADER_DOTS_PATTERN = re.compile(r"\.{2,}\s*\d{1,4}\s*$")
TRAILING_PAGE_PATTERN = re.compile(r"\d{1,4}\s*$")
NUMBERED_TOC_PATTERN = re.compile(
    r"^(?:\d+(?:\.\d+){0,5}[.)]?|chapter\s+\d+(?::|\.)?)\s+\S.*\d{1,4}\s*$",
    re.IGNORECASE,
)
SPACED_PAGE_PATTERN = re.compile(r"^.+\s{2,}\d{1,4}\s*$")
TRAILING_NUMERIC_REFERENCE_PATTERN = re.compile(
    r"^(?:.+?)(?:\.{2,}\s*|\s{2,})\d{1,4}\s*$",
)


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


def max_toc_scan_pages(page_count: int) -> int:
    """Return the conservative leading-page cap for TOC detection."""

    return min(page_count, MAX_TOC_SCAN_PAGES)


def extract_toc_like_lines(page: PageArtifacts) -> tuple[str, ...]:
    """Return lines that resemble TOC entries on a page."""

    lines = split_text_lines_with_offsets(page.text, page.page_index)
    matches: list[str] = []
    for line in lines:
        if _is_toc_like_line(line.text):
            matches.append(line.text)
    return tuple(matches)


def _is_toc_like_line(text: str) -> bool:
    if LEADER_DOTS_PATTERN.search(text):
        return True
    if NUMBERED_TOC_PATTERN.match(text):
        return True
    return bool(SPACED_PAGE_PATTERN.match(text))


def leader_dot_density(page: PageArtifacts) -> float:
    """Return the normalized density of TOC-like lines with leader dots."""

    toc_like_lines = extract_toc_like_lines(page)
    if not toc_like_lines:
        return 0.0
    leader_matches = sum(1 for line in toc_like_lines if LEADER_DOTS_PATTERN.search(line))
    return min(1.0, leader_matches / len(toc_like_lines))


def numbering_density(page: PageArtifacts) -> float:
    """Return the normalized density of TOC-like lines with numbering prefixes."""

    toc_like_lines = extract_toc_like_lines(page)
    if not toc_like_lines:
        return 0.0
    numbered_matches = sum(1 for line in toc_like_lines if NUMBERED_TOC_PATTERN.match(line))
    return min(1.0, numbered_matches / len(toc_like_lines))


def font_uniformity_signal(page: PageArtifacts) -> float:
    """Return a font-uniformity signal for rawdict-backed TOC-like lines."""

    text_lines = split_text_lines_with_offsets(page.text, page.page_index)
    rawdict_lines = extract_rawdict_lines(page.rawdict, page.page_index, text_lines)
    if getattr(page, "canonical_lines", ()):
        _, rawdict_lines = _line_lists_for_page(page)
    if not rawdict_lines:
        return 0.0
    toc_like_lines = {
        line.normalized_text
        for line in rawdict_lines
        if _is_toc_like_line(line.text) and line.font_size is not None
    }
    if not toc_like_lines:
        return 0.0

    size_buckets: dict[float, int] = {}
    matched_count = 0
    for line in rawdict_lines:
        if (
            line.normalized_text not in toc_like_lines
            or line.font_size is None
            or not _is_toc_like_line(line.text)
        ):
            continue
        bucket = round(line.font_size, 1)
        size_buckets[bucket] = size_buckets.get(bucket, 0) + 1
        matched_count += 1
    if matched_count < 2:
        return 0.0
    return min(1.0, max(size_buckets.values()) / matched_count)


def has_page_numbers_in_toc_content(toc_content: str | None) -> bool:
    """Return whether TOC content includes at least two distinct page-number lines."""

    if toc_content is None:
        return False
    matched_lines = {
        line.strip()
        for line in toc_content.splitlines()
        if TRAILING_NUMERIC_REFERENCE_PATTERN.match(line.strip())
    }
    return len(matched_lines) >= 2


def _classification_reason(
    *,
    pattern_match_count: int,
    leader_dot_density_value: float,
    numbering_density_value: float,
    font_uniformity_value: float,
    repeated_penalty: float,
) -> list[str]:
    reasons: list[str] = []
    if pattern_match_count:
        reasons.append(f"pattern_match_count:{pattern_match_count}")
    if leader_dot_density_value > 0:
        reasons.append("leader_dots")
    if numbering_density_value > 0:
        reasons.append("numbering_prefixes")
    if font_uniformity_value > 0:
        reasons.append("font_uniformity")
    if repeated_penalty > 0:
        reasons.append("repeated_header_penalty")
    return reasons


def _base_final_score(
    *,
    pattern_match_count: int,
    leader_dot_density_value: float,
    numbering_density_value: float,
    font_uniformity_value: float,
    repeated_penalty: float,
) -> float:
    pattern_density = min(1.0, pattern_match_count / 3.0)
    weighted_score = (
        (pattern_density * PATTERN_MATCH_WEIGHT)
        + (leader_dot_density_value * LEADER_DOT_WEIGHT)
        + (numbering_density_value * NUMBERING_WEIGHT)
        + (font_uniformity_value * FONT_UNIFORMITY_WEIGHT)
        - (repeated_penalty * REPEATED_HEADER_PENALTY_WEIGHT)
    )
    return min(1.0, max(0.0, weighted_score))


def _apply_consecutive_page_bonus(base_scores: list[TocPageScore]) -> list[TocPageScore]:
    updated_scores: list[TocPageScore] = []
    previous_confident = False
    for score in base_scores:
        bonus = 0.0
        if previous_confident and score.final_score >= DETERMINISTIC_LOW_THRESHOLD:
            bonus = CONSECUTIVE_PAGE_WEIGHT
        final_score = min(1.0, score.final_score + bonus)
        updated = score.model_copy(
            update={
                "consecutive_page_bonus": bonus,
                "final_score": final_score,
            }
        )
        updated_scores.append(updated)
        previous_confident = final_score >= DETERMINISTIC_HIGH_THRESHOLD
    return updated_scores


class TocDetector:
    """Deterministic-first TOC detector with optional typed LLM fallback."""

    def __init__(
        self,
        settings: TreeSettings,
        gateway: StructuredLLMGateway | None = None,
    ) -> None:
        self._settings = settings
        self._gateway = gateway

    def detect(
        self,
        *,
        pages: tuple[PageArtifacts, ...],
        artifact_root: str | None = None,
    ) -> TocDetectionResult:
        inspected_pages = pages[: max_toc_scan_pages(len(pages))]
        repeated_lines = find_repeated_header_footer_lines(inspected_pages, self._settings)
        base_scores: list[TocPageScore] = []

        for page in inspected_pages:
            toc_lines = extract_toc_like_lines(page)
            text_lines = split_text_lines_with_offsets(page.text, page.page_index)
            repeated_penalty = 0.0
            if any(line.normalized_text in repeated_lines for line in text_lines):
                repeated_penalty = 1.0
            leader_density = leader_dot_density(page)
            numbering_density_value = numbering_density(page)
            font_signal = font_uniformity_signal(page)
            final_score = _base_final_score(
                pattern_match_count=len(toc_lines),
                leader_dot_density_value=leader_density,
                numbering_density_value=numbering_density_value,
                font_uniformity_value=font_signal,
                repeated_penalty=repeated_penalty,
            )
            base_scores.append(
                TocPageScore(
                    page_index=page.page_index,
                    pattern_match_count=len(toc_lines),
                    leader_dot_density=leader_density,
                    numbering_density=numbering_density_value,
                    font_uniformity_signal=font_signal,
                    repeated_header_penalty=repeated_penalty,
                    final_score=final_score,
                    classification_reason=tuple(
                        _classification_reason(
                            pattern_match_count=len(toc_lines),
                            leader_dot_density_value=leader_density,
                            numbering_density_value=numbering_density_value,
                            font_uniformity_value=font_signal,
                            repeated_penalty=repeated_penalty,
                        )
                    ),
                )
            )

        scored_pages = _apply_consecutive_page_bonus(base_scores)
        final_scores: list[TocPageScore] = []
        llm_calls = 0
        llm_positive_pages = 0
        deterministic_positive_pages = 0

        for page, score in zip(inspected_pages, scored_pages, strict=True):
            reasons = list(score.classification_reason)
            classified_as_toc = False
            if score.final_score >= DETERMINISTIC_HIGH_THRESHOLD:
                classified_as_toc = True
                deterministic_positive_pages += 1
                reasons.append("deterministic_high_threshold")
            elif score.final_score < DETERMINISTIC_LOW_THRESHOLD:
                reasons.append("deterministic_low_threshold")
            elif self._gateway is not None:
                llm_calls += 1
                response = self._gateway.invoke(
                    GatewayRequest[TocDetectionResponse](
                        operation_name="toc_detection",
                        messages=build_toc_detection_messages(page_text=page.text),
                        response_model=TocDetectionResponse,
                    )
                ).output
                classified_as_toc = response.is_toc
                if response.is_toc:
                    llm_positive_pages += 1
                    reasons.append("llm_positive")
                else:
                    reasons.append("llm_negative")
            else:
                reasons.append("ambiguous_without_gateway")

            final_scores.append(
                score.model_copy(
                    update={
                        "classified_as_toc": classified_as_toc,
                        "classification_reason": tuple(reasons),
                    }
                )
            )

        toc_page_indices: list[int] = []
        toc_pages: list[str] = []
        in_toc_run = False
        for page, score in zip(inspected_pages, final_scores, strict=True):
            if score.classified_as_toc:
                in_toc_run = True
                toc_page_indices.append(page.page_index)
                toc_pages.append(page.text)
                continue
            if in_toc_run and score.final_score < DETERMINISTIC_LOW_THRESHOLD:
                break

        toc_content = "\n\n".join(toc_pages) if toc_pages else None
        if llm_calls == 0:
            detection_method = TocDetectionMethod.DETERMINISTIC
        elif deterministic_positive_pages == 0 and llm_positive_pages > 0:
            detection_method = TocDetectionMethod.LLM_ONLY
        else:
            detection_method = TocDetectionMethod.HYBRID

        result = TocDetectionResult(
            toc_page_indices=tuple(toc_page_indices),
            toc_content=toc_content,
            detection_method=detection_method,
            page_scores=tuple(final_scores),
            has_page_numbers=has_page_numbers_in_toc_content(toc_content),
        )
        if artifact_root is not None:
            _write_json(Path(artifact_root) / "toc-detection.json", result)
        return result
