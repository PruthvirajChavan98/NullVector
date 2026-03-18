"""Typed document-description prompt artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.llm.audit import json_safe
from nullvector.llm.types import LLMMessage, LLMRole


class DocumentDescriptionPromptResponse(NullVectorModel):
    """Structured response expected from the document-description prompt."""

    description_text: NonEmptyStr
    supporting_node_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


def build_document_description_messages(
    *,
    document_id: str,
    source_nodes: Sequence[Mapping[str, Any]],
) -> tuple[LLMMessage, ...]:
    """Build a grounded, bounded document-description prompt."""

    payload = json.dumps(
        {
            "document_id": document_id,
            "source_nodes": [json_safe(node) for node in source_nodes],
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are generating a short document description for NullVector. "
                "Use only the supplied node data. "
                "Do not invent sections, facts, scope, or provenance. "
                "Return a concise differentiating description and only cite supporting_node_ids "
                "from the provided source_nodes."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                "Return a structured document description for the document below.\n"
                "The description should be short, human-readable, and focused on what makes "
                "this document distinct.\n\n"
                f"{payload}"
            ),
        ),
    )


__all__ = [
    "DocumentDescriptionPromptResponse",
    "build_document_description_messages",
]
