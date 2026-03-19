"""Typed prompt artifacts for preference-aware tree-search frontier selection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.domain.retrieval import TreeSearchTerminationSignal
from nullvector.llm.audit import json_safe
from nullvector.llm.types import LLMMessage, LLMRole


class PreferenceTreeSearchFrontierPromptResponse(NullVectorModel):
    """Structured response expected from one preference-aware tree-search prompt."""

    selected_node_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    selection_reason: NonEmptyStr
    termination_signal: TreeSearchTerminationSignal | None = None
    applied_preference_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


def build_preference_tree_search_frontier_messages(
    *,
    query: str,
    normalized_query: str,
    frontier_nodes: Sequence[Mapping[str, Any]],
    preference_snippets: Sequence[Mapping[str, Any]],
    current_depth: int,
    max_depth: int,
) -> tuple[LLMMessage, ...]:
    """Build a bounded prompt for one preference-aware tree-search frontier step."""

    payload = json.dumps(
        {
            "query": query,
            "normalized_query": normalized_query,
            "current_depth": current_depth,
            "max_depth": max_depth,
            "preference_snippets": [json_safe(snippet) for snippet in preference_snippets],
            "frontier_nodes": [json_safe(node) for node in frontier_nodes],
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are selecting the most relevant tree nodes for NullVector retrieval while "
                "respecting the supplied preference snippets. Use only the provided frontier "
                "nodes and preference snippets. Do not invent node IDs, preference IDs, or "
                "source content. Choose up to two node_ids from the frontier. Return only "
                "applied_preference_ids that are actually relevant to your selection."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                "Return a structured preference-aware tree-search frontier selection for the "
                f"payload below.\n\n{payload}"
            ),
        ),
    )


__all__ = [
    "PreferenceTreeSearchFrontierPromptResponse",
    "build_preference_tree_search_frontier_messages",
]
