"""Gateway-shaped structured response models shared by prompt builders and services."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.domain.tree import DecompositionBoundary, TocParsedEntry


class TocDetectionResponse(NullVectorModel):
    """Typed structured response for ambiguous TOC page detection."""

    is_toc: bool
    confidence: float
    reasoning: NonEmptyStr

    @model_validator(mode="after")
    def validate_confidence(self) -> Self:
        if not 0 <= self.confidence <= 1:
            msg = "confidence must be between 0 and 1"
            raise ValueError(msg)
        return self


class TocParseResponse(NullVectorModel):
    """Typed structured TOC parsing response from the gateway."""

    entries: tuple[TocParsedEntry, ...]


class DecompositionPromptResponse(NullVectorModel):
    """Typed structured response for large-node decomposition."""

    entries: tuple[DecompositionBoundary, ...] = ()


__all__ = [
    "DecompositionPromptResponse",
    "TocDetectionResponse",
    "TocParseResponse",
]
