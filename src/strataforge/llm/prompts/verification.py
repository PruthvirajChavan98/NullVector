"""Typed verification-assistance prompt artifacts."""

from __future__ import annotations

import json

from strataforge.domain.models import NonEmptyStr, StrataModel
from strataforge.llm.types import LLMMessage, LLMRole


class VerificationPromptResponse(StrataModel):
    """Typed verification-assistance output for future phases."""

    verdict: NonEmptyStr
    rationale: NonEmptyStr
    supporting_quotes: tuple[NonEmptyStr, ...] = ()


def build_verification_messages(
    *,
    title: str,
    page_excerpt: str,
    expected_span: tuple[int, int],
) -> tuple[LLMMessage, ...]:
    """Build bounded verification-assistance messages without free-form synthesis."""

    payload = json.dumps(
        {
            "title": title,
            "page_excerpt": page_excerpt,
            "expected_span": [expected_span[0], expected_span[1]],
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are assisting bounded verification. "
                "Use only the supplied excerpt and span. "
                "Do not invent provenance, spans, or document structure."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=f"Return a structured verification assessment for:\n{payload}",
        ),
    )
