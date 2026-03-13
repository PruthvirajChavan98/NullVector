"""Compatibility facade for semantic summarization."""

from nullvector.semantic.summarize import (
    LEAF_PASSTHROUGH_TOKEN_THRESHOLD,
    NodeSummarizer,
    estimate_token_count,
)

__all__ = [
    "LEAF_PASSTHROUGH_TOKEN_THRESHOLD",
    "NodeSummarizer",
    "estimate_token_count",
]
