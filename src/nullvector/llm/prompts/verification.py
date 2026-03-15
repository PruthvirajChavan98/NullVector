"""Typed verification-assistance prompt artifacts."""

from __future__ import annotations

import json

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.llm.types import LLMMessage, LLMRole


class VerificationPromptResponse(NullVectorModel):
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
                "Do not invent provenance, spans, or document structure. "
                "Return verdict as exactly yes or no."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                f'Does the section titled "{title}" begin on this page? '
                "Only use the provided text. Do not infer from outside knowledge.\n\n"
                "Return a structured verification assessment for:\n"
                f"{payload}"
            ),
        ),
    )
