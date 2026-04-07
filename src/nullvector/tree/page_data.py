"""Minimal page data container for VLM/LLM-driven tree synthesis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageData:
    """Lightweight page substrate replacing the deterministic PageArtifacts.

    Contains only the text content needed for LLM-driven hierarchy and
    summarization.  No bounding boxes, rawdict, or font-size data.
    """

    page_index: int
    text: str
    page_label: str | None = None
