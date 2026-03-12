"""Semantic compression and enrichment boundaries."""

from __future__ import annotations

from typing import Any

from strataforge.semantic.tokens import (
    HeuristicTokenizer,
    OptionalExactTokenizer,
    Tokenizer,
    resolve_tokenizer,
)

__all__ = [
    "HeuristicTokenizer",
    "NodeDecomposer",
    "NodeSummarizer",
    "OptionalExactTokenizer",
    "Tokenizer",
    "estimate_token_count",
    "resolve_tokenizer",
]


def __getattr__(name: str) -> Any:
    if name in {"NodeDecomposer"}:
        from strataforge.semantic.decompose import NodeDecomposer

        return NodeDecomposer
    if name in {"NodeSummarizer", "estimate_token_count"}:
        from strataforge.semantic.summarize import NodeSummarizer, estimate_token_count

        return {"NodeSummarizer": NodeSummarizer, "estimate_token_count": estimate_token_count}[
            name
        ]
    raise AttributeError(name)
