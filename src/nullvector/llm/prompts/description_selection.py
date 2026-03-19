"""Typed description-selection prompt artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field, NonNegativeFloat

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.llm.audit import json_safe
from nullvector.llm.types import LLMMessage, LLMRole


class DescriptionSelectionPromptCandidate(NullVectorModel):
    """One structured candidate returned by a description-selection prompt."""

    document_id: NonEmptyStr
    reason: NonEmptyStr
    relevance_score: NonNegativeFloat


class DescriptionSelectionPromptResponse(NullVectorModel):
    """Structured response expected from the description-selection prompt."""

    candidates: tuple[DescriptionSelectionPromptCandidate, ...] = Field(default_factory=tuple)


def build_description_selection_messages(
    *,
    query: str,
    descriptions: Sequence[Mapping[str, Any]],
) -> tuple[LLMMessage, ...]:
    """Build a bounded prompt for collection-level description selection."""

    payload = json.dumps(
        {
            "query": query,
            "descriptions": [json_safe(description) for description in descriptions],
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are ranking document descriptions for NullVector before retrieval. "
                "Use only the supplied descriptions. "
                "Do not invent document IDs, metadata, or evidence. "
                "Return only candidate document_ids from the provided descriptions, "
                "ordered by relevance."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                "Return structured description-selection candidates for the payload below.\n\n"
                f"{payload}"
            ),
        ),
    )


__all__ = [
    "DescriptionSelectionPromptCandidate",
    "DescriptionSelectionPromptResponse",
    "build_description_selection_messages",
]
