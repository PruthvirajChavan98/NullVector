"""Typed parse substrate errors."""

from __future__ import annotations

from strataforge.domain.models import ParseErrorCode, ParseFailure


class ParseSubstrateError(Exception):
    """Base class for deterministic parser substrate failures."""

    def __init__(self, failure: ParseFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


class InvalidSourceError(ParseSubstrateError):
    """Raised when a source PDF cannot be read or fingerprinted."""

    def __init__(self, message: str, *, source_path: str) -> None:
        super().__init__(
            ParseFailure(
                code=ParseErrorCode.INVALID_SOURCE,
                message=message,
                details={"source_path": source_path},
            ),
        )


class ParseConflictError(ParseSubstrateError):
    """Raised when a parse run id is reused with different effective inputs."""

    def __init__(self, message: str, *, parse_run_id: str, document_id: str) -> None:
        super().__init__(
            ParseFailure(
                code=ParseErrorCode.CONFLICT,
                message=message,
                document_id=document_id,
                details={"parse_run_id": parse_run_id},
            ),
        )


class MissingOcrRuntimeError(ParseSubstrateError):
    """Raised when OCR is needed but Tesseract/tessdata is unavailable."""

    def __init__(self, message: str, *, page_index: int, document_id: str) -> None:
        super().__init__(
            ParseFailure(
                code=ParseErrorCode.MISSING_OCR_RUNTIME,
                message=message,
                document_id=document_id,
                page_index=page_index,
            ),
        )


class ExtractionFailureError(ParseSubstrateError):
    """Raised when a parser/OCR operation fails unexpectedly."""

    def __init__(self, message: str, *, document_id: str, page_index: int | None = None) -> None:
        super().__init__(
            ParseFailure(
                code=ParseErrorCode.EXTRACTION_FAILED,
                message=message,
                document_id=document_id,
                page_index=page_index,
            ),
        )
