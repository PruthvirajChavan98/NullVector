"""Structured logging helpers for NullVector runtime observability."""

from __future__ import annotations

import logging
import os
from typing import Any

from nullvector.observability.subscribers.json_logger import configure_jsonl_logger
from nullvector.observability.subscribers.rich_progress import configure_progress_logger

DEFAULT_OBSERVABILITY_LOGGER_NAME = "nullvector"
DEFAULT_OBSERVABILITY_JSONL_PATH = "artifacts/observability/nullvector-events.jsonl"
_OBSERVABILITY_DISABLE_ENV = "NULLVECTOR_OBSERVABILITY_DISABLE"
_OBSERVABILITY_JSONL_ENV = "NULLVECTOR_OBSERVABILITY_JSONL_PATH"
_OBSERVABILITY_LEVEL_ENV = "NULLVECTOR_OBSERVABILITY_LEVEL"


def get_logger(name: str = DEFAULT_OBSERVABILITY_LOGGER_NAME) -> logging.Logger:
    """Return the canonical NullVector logger."""

    return logging.getLogger(name)


def configure_default_runtime_observability(
    *,
    logger: logging.Logger | None = None,
    jsonl_path: str | None = None,
    stream: Any | None = None,
    level: int | str | None = None,
) -> logging.Logger | None:
    """Return the canonical default runtime logger with progress + JSONL handlers.

    The helper is intentionally idempotent so repeated service construction or
    notebook execution does not duplicate managed handlers.
    """

    configured_logger = logger or get_logger()
    if _observability_disabled():
        _remove_managed_handlers(configured_logger)
        return None

    resolved_level = _resolve_level(level)
    resolved_jsonl_path = (
        jsonl_path or os.environ.get(_OBSERVABILITY_JSONL_ENV) or DEFAULT_OBSERVABILITY_JSONL_PATH
    )
    configure_progress_logger(
        logger=configured_logger,
        stream=stream,
        level=resolved_level,
    )
    configure_jsonl_logger(
        resolved_jsonl_path,
        logger=configured_logger,
        level=resolved_level,
    )
    configured_logger.setLevel(resolved_level)
    configured_logger.propagate = False
    return configured_logger


def resolve_runtime_logger(logger: logging.Logger | None) -> logging.Logger | None:
    """Resolve ``None`` to the default runtime logger, respecting opt-out env flags."""

    if logger is not None:
        return logger
    return configure_default_runtime_observability()


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


def _observability_disabled() -> bool:
    return os.environ.get(_OBSERVABILITY_DISABLE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolve_level(level: int | str | None) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str) and level.strip():
        normalized = level.strip().upper()
    else:
        normalized = os.environ.get(_OBSERVABILITY_LEVEL_ENV, "INFO").strip().upper() or "INFO"
    mapping = logging.getLevelNamesMapping()
    if normalized not in mapping:
        msg = f"unsupported NULLVECTOR_OBSERVABILITY_LEVEL value: {normalized!r}"
        raise ValueError(msg)
    return mapping[normalized]


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in tuple(logger.handlers):
        if not (
            getattr(handler, "_nullvector_progress_handler", False)
            or getattr(handler, "_nullvector_jsonl_handler", False)
        ):
            continue
        logger.removeHandler(handler)
        handler.close()


__all__ = [
    "DEFAULT_OBSERVABILITY_JSONL_PATH",
    "DEFAULT_OBSERVABILITY_LOGGER_NAME",
    "configure_default_runtime_observability",
    "get_logger",
    "log_event",
    "resolve_runtime_logger",
]
