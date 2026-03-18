"""Typed metadata-selection prompt artifacts."""

from __future__ import annotations

import json

from pydantic import Field

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.domain.document_selection import (
    DocumentFilterClause,
    DocumentFilterOperator,
)
from nullvector.llm.audit import json_safe
from nullvector.llm.types import LLMMessage, LLMRole


class MetadataSelectionPromptResponse(NullVectorModel):
    """Structured response expected from metadata-selection planning prompts."""

    normalized_query: NonEmptyStr
    clauses: tuple[DocumentFilterClause, ...] = Field(default_factory=tuple)
    reasoning_summary: NonEmptyStr | None = None


def build_metadata_selection_messages(
    *,
    query: str,
    allowed_fields: tuple[str, ...],
    allowed_operators: tuple[DocumentFilterOperator, ...],
    field_descriptions: dict[str, str],
) -> tuple[LLMMessage, ...]:
    """Build a bounded natural-language-to-metadata-selection prompt."""

    payload = json.dumps(
        {
            "query": query,
            "allowed_fields": allowed_fields,
            "allowed_operators": tuple(operator.value for operator in allowed_operators),
            "field_descriptions": json_safe(field_descriptions),
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are translating a user query into typed NullVector metadata filters. "
                "Only use the supplied fields and operators. "
                "Do not invent schema fields or unsupported operators. "
                "Return empty clauses when metadata is not a reliable narrowing signal."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                "Return a structured metadata selection plan for the payload below.\n\n"
                f"{payload}"
            ),
        ),
    )


__all__ = [
    "MetadataSelectionPromptResponse",
    "build_metadata_selection_messages",
]
