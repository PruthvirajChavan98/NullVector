"""Structured logging helpers for NullVector runtime observability."""

from __future__ import annotations

import logging
from typing import Any


def get_logger(name: str = "nullvector") -> logging.Logger:
    """Return the canonical NullVector logger."""

    return logging.getLogger(name)


def log_event(
    logger: logging.Logger | None,
    event_name: str,
    *,
    document_id: str = "",
    **fields: Any,
) -> None:
    """Emit one structured runtime event when logging is enabled."""

    if logger is None:
        return
    payload = {
        "event_name": event_name,
        "document_id": document_id,
        **fields,
    }
    logger.info(event_name, extra={"nullvector_event": payload})


__all__ = [
    "get_logger",
    "log_event",
]
