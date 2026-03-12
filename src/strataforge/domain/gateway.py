"""Gateway-shaped structured response models shared by prompt builders and services."""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from strataforge.domain.common import NonEmptyStr, StrataModel
from strataforge.domain.tree import DecompositionBoundary, TocParsedEntry


class TocDetectionResponse(StrataModel):
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


class TocParseResponse(StrataModel):
    """Typed structured TOC parsing response from the gateway."""

    entries: tuple[TocParsedEntry, ...]


class DecompositionPromptResponse(StrataModel):
    """Typed structured response for large-node decomposition."""

    entries: tuple[DecompositionBoundary, ...] = ()


__all__ = [
    "DecompositionPromptResponse",
    "TocDetectionResponse",
    "TocParseResponse",
]
