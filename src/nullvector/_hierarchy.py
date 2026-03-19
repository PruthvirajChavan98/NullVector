"""Shared hierarchy ordering helpers used across tree and retrieval services."""

from __future__ import annotations

from nullvector.domain.common import PageSpan


def document_order_key(
    *,
    page_span: PageSpan,
    level: int,
    path: tuple[str, ...],
    identifier: str,
) -> tuple[int, int, int, tuple[str, ...], str]:
    """Return a stable document-order key for tree-shaped records."""

    return (
        page_span.start_page,
        page_span.end_page,
        level,
        path,
        identifier,
    )


def path_has_prefix(candidate: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    """Return whether one hierarchy path is a strict descendant of another."""

    return len(candidate) > len(prefix) and candidate[: len(prefix)] == prefix


__all__ = ["document_order_key", "path_has_prefix"]
