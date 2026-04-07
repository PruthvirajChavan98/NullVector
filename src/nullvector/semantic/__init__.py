"""Semantic compression and enrichment boundaries."""

from __future__ import annotations

from typing import Any

__all__ = [
    "NodeDecomposer",
    "NodeSummarizer",
    "estimate_token_count",
]


def __getattr__(name: str) -> Any:
    if name == "NodeDecomposer":
        from nullvector.semantic.decompose import NodeDecomposer

        return NodeDecomposer
    if name in {"NodeSummarizer", "estimate_token_count"}:
        from nullvector.semantic.summarize import NodeSummarizer, estimate_token_count

        return {"NodeSummarizer": NodeSummarizer, "estimate_token_count": estimate_token_count}[
            name
        ]
    raise AttributeError(name)
