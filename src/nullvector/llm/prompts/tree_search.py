"""Typed prompt artifacts for bounded tree-search frontier selection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.domain.retrieval import TreeSearchTerminationSignal
from nullvector.llm.audit import json_safe
from nullvector.llm.types import LLMMessage, LLMRole


class TreeSearchFrontierPromptResponse(NullVectorModel):
    """Structured response expected from one tree-search frontier prompt."""

    selected_node_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    selection_reason: NonEmptyStr
    termination_signal: TreeSearchTerminationSignal | None = None


def build_tree_search_frontier_messages(
    *,
    query: str,
    normalized_query: str,
    frontier_nodes: Sequence[Mapping[str, Any]],
    current_depth: int,
    max_depth: int,
) -> tuple[LLMMessage, ...]:
    """Build a bounded prompt for one tree-search frontier step."""

    payload = json.dumps(
        {
            "query": query,
            "normalized_query": normalized_query,
            "current_depth": current_depth,
            "max_depth": max_depth,
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
                "You are selecting the most relevant tree nodes for NullVector retrieval. "
                "Use only the provided frontier nodes. "
                "Do not invent node IDs or source content. "
                "Choose up to two node_ids from the frontier. "
                "If search should continue deeper, return termination_signal as null. "
                "If search should stop, return one of the allowed termination signals."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                "Return a structured tree-search frontier selection for the payload below.\n\n"
                f"{payload}"
            ),
        ),
    )


__all__ = [
    "TreeSearchFrontierPromptResponse",
    "build_tree_search_frontier_messages",
]
