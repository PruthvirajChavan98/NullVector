"""Gateway-shaped structured response models shared by prompt builders and services."""

from __future__ import annotations

from pydantic import NonNegativeInt, PositiveInt

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.domain.tree import DecompositionBoundary


class DecompositionPromptResponse(NullVectorModel):
    """Typed structured response for large-node decomposition."""

    entries: tuple[DecompositionBoundary, ...] = ()


class VLMTranscriptionResponse(NullVectorModel):
    """Typed structured response for VLM page transcription."""

    markdown_text: NonEmptyStr
    has_tables: bool = False
    has_images: bool = False


class HierarchySynthesisNode(NullVectorModel):
    """Single node in an LLM-synthesized document hierarchy."""

    title: NonEmptyStr
    level: PositiveInt
    start_page: NonNegativeInt
    end_page: NonNegativeInt
    summary_hint: str | None = None


class HierarchySynthesisResponse(NullVectorModel):
    """Typed structured response for LLM hierarchy synthesis."""

    nodes: tuple[HierarchySynthesisNode, ...] = ()


__all__ = [
    "DecompositionPromptResponse",
    "HierarchySynthesisNode",
    "HierarchySynthesisResponse",
    "VLMTranscriptionResponse",
]
