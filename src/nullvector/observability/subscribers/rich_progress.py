"""Human-readable progress logging configuration for local runs."""

from __future__ import annotations

import logging
import sys
from typing import TextIO


class ProgressEventFormatter(logging.Formatter):
    """Render structured events as lightweight progress lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "nullvector_event", None)
        if payload is None:
            return record.getMessage()
        return f"[{payload['event_name']}] document={payload['document_id']}"


def configure_progress_logger(
    *,
    logger: logging.Logger | None = None,
    stream: TextIO | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Attach a progress-stream handler to the provided logger."""

    configured_logger = logger or logging.getLogger("nullvector")
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(ProgressEventFormatter())
    configured_logger.addHandler(handler)
    configured_logger.setLevel(level)
    configured_logger.propagate = False
    return configured_logger


__all__ = ["ProgressEventFormatter", "configure_progress_logger"]
