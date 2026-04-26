"""Shared text extraction helpers for semantic tree operations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from nullvector.domain.common import ContentSpan
from nullvector.domain.tree import HierarchyNode


class _TextPage(Protocol):
    page_index: int
    text: str


def _non_empty_span(span: ContentSpan) -> bool:
    if span.end_page < span.start_page:
        return False
    return not (span.start_page == span.end_page and span.end_offset <= span.start_offset)


def _owned_content_spans(node: HierarchyNode) -> tuple[ContentSpan, ...]:
    return tuple(span.span for span in node.owned_spans if _non_empty_span(span.span))


def text_for_content_span(
    *,
    pages_by_index: Mapping[int, _TextPage],
    span: ContentSpan,
) -> str:
    parts: list[str] = []
    for page_index in range(span.start_page, span.end_page + 1):
        page = pages_by_index.get(page_index)
        if page is None:
            continue
        start_offset = 0
        end_offset = len(page.text)
        if page_index == span.start_page:
            start_offset = min(span.start_offset, len(page.text))
        if page_index == span.end_page:
            end_offset = min(span.end_offset, len(page.text))
        if start_offset >= end_offset:
            continue
        parts.append(page.text[start_offset:end_offset].strip())
    return "\n".join(part for part in parts if part).strip()


def text_fragments_for_node(
    node: HierarchyNode,
    pages_by_index: Mapping[int, _TextPage],
) -> tuple[str, ...]:
    owned_spans = _owned_content_spans(node)
    if owned_spans:
        fragments = tuple(
            text_for_content_span(pages_by_index=pages_by_index, span=span) for span in owned_spans
        )
        non_empty = tuple(fragment for fragment in fragments if fragment)
        if non_empty:
            return non_empty
    return tuple(
        pages_by_index[page_index].text.strip()
        for page_index in range(node.page_span.start_page, node.page_span.end_page + 1)
        if page_index in pages_by_index and pages_by_index[page_index].text.strip()
    )


def text_for_node(
    node: HierarchyNode,
    pages_by_index: Mapping[int, _TextPage],
) -> str:
    return "\n".join(text_fragments_for_node(node, pages_by_index)).strip()


def bounded_fragments(
    fragments: Iterable[str],
    *,
    max_chars: int,
) -> tuple[str, ...]:
    selected: list[str] = []
    remaining = max_chars
    for fragment in fragments:
        if remaining <= 0:
            break
        excerpt = fragment[:remaining].strip()
        if not excerpt:
            continue
        selected.append(excerpt)
        remaining -= len(excerpt)
    return tuple(selected)


__all__ = [
    "bounded_fragments",
    "text_for_content_span",
    "text_for_node",
    "text_fragments_for_node",
]
