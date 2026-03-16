"""Shared domain primitives and strict base models."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Generic, Self, TypeAlias, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    model_validator,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256Hex = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-f0-9]{64}$"),
]
ScalarValue: TypeAlias = str | int | float | bool | None


class GeometryCoordinateSpace(StrEnum):
    """Canonical coordinate space for persisted geometry artifacts."""

    UNROTATED_PAGE = "unrotated_page"


class NullVectorModel(BaseModel):
    """Strict frozen base for all NullVector domain models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class BoundingBox(NullVectorModel):
    """Axis-aligned page-local bounding box."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.x1 < self.x0:
            msg = "x1 must be greater than or equal to x0"
            raise ValueError(msg)
        if self.y1 < self.y0:
            msg = "y1 must be greater than or equal to y0"
            raise ValueError(msg)
        return self


class PageSpan(NullVectorModel):
    """Inclusive page span within a source document."""

    start_page: NonNegativeInt
    end_page: NonNegativeInt

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.end_page < self.start_page:
            msg = "end_page must be greater than or equal to start_page"
            raise ValueError(msg)
        return self


class PageSourceAnchor(NullVectorModel):
    """Grounding anchor for summaries and verification."""

    page: NonNegativeInt
    start_offset: NonNegativeInt
    end_offset: PositiveInt
    quote: NonEmptyStr

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end_offset <= self.start_offset:
            msg = "end_offset must be greater than start_offset"
            raise ValueError(msg)
        return self


class ContentSpan(NullVectorModel):
    """Offset-aware inclusive/exclusive span within the document."""

    start_page: NonNegativeInt
    start_offset: NonNegativeInt
    end_page: NonNegativeInt
    end_offset: NonNegativeInt

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.end_page < self.start_page:
            msg = "end_page must be greater than or equal to start_page"
            raise ValueError(msg)
        if self.start_page == self.end_page and self.end_offset < self.start_offset:
            msg = "end_offset must be greater than or equal to start_offset on same-page spans"
            raise ValueError(msg)
        return self


class NodeOwnedSpan(NullVectorModel):
    """Explicit content ownership span for decomposition-aware nodes."""

    span: ContentSpan
    kind: NonEmptyStr


_T = TypeVar("_T")


class BatchItemFailure(NullVectorModel):
    """Records a single-item failure within a batch pipeline operation."""

    item_index: NonNegativeInt
    error_type: NonEmptyStr
    error_message: NonEmptyStr


class BatchResult(BaseModel, Generic[_T]):
    """Typed envelope for the outcome of a batch pipeline operation.

    Uses ``BaseModel`` directly (not ``NullVectorModel``) because ``strict=True``
    on a Generic container causes TypeVar resolution friction with Pydantic v2.
    ``frozen=True`` and ``extra="forbid"`` are still enforced via ``ConfigDict``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    successful: tuple[_T, ...]
    failed: tuple[BatchItemFailure, ...]


__all__ = [
    "BatchItemFailure",
    "BatchResult",
    "BoundingBox",
    "ContentSpan",
    "GeometryCoordinateSpace",
    "NodeOwnedSpan",
    "NonEmptyStr",
    "NullVectorModel",
    "PageSourceAnchor",
    "PageSpan",
    "ScalarValue",
    "Sha256Hex",
]
