"""Typed prompt builder for bounded large-node decomposition."""

from __future__ import annotations

from strataforge.llm.types import LLMMessage, LLMRole


def build_decomposition_messages(
    *,
    node_title: str,
    page_text: str,
) -> tuple[LLMMessage, ...]:
    """Build bounded messages for subsection-boundary discovery inside one node."""

    return (
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "You are assisting bounded hierarchy decomposition for StrataForge. "
                "Only identify subsection boundaries that are visibly supported by the "
                "supplied page text. Use the <page_N> markers exactly as the physical "
                "page indices for any returned entries. If the evidence is weak, return "
                "an empty entries list. Return only the structured schema."
            ),
        ),
        LLMMessage(
            role=LLMRole.USER,
            content=(
                f"Current node title: {node_title}\n\n"
                "Inspect the bounded page text below and return only visible subsection "
                "boundaries.\n\n"
                f"{page_text}"
            ),
        ),
    )
