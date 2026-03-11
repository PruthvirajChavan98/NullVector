"""Typed summarization prompt artifacts for later phases."""

from __future__ import annotations

import json

from strataforge.domain.models import NonEmptyStr, StrataModel
from strataforge.llm.types import LLMMessage, LLMRole


class SummarizationPromptResponse(StrataModel):
    """Typed summarization output for later workflow phases."""

    summary: NonEmptyStr
    keywords: tuple[NonEmptyStr, ...] = ()


def build_summarization_messages(
    *,
    node_title: str,
    excerpts: tuple[str, ...],
) -> tuple[LLMMessage, ...]:
    """Build a grounded summarization prompt with bounded evidence only."""

    payload = json.dumps(
        {
            "node_title": node_title,
            "excerpts": list(excerpts),
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are producing a grounded node summary. "
                "Use only the supplied excerpts and do not invent facts or provenance."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=f"Return a structured summary for:\n{payload}",
        ),
    )
