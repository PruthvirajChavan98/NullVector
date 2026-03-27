"""JSONL logging configuration for structured runtime events."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from nullvector.runtime_validation import validate_writable_root
from nullvector.storage._serialization import json_safe

_JSONL_HANDLER_ATTR = "_nullvector_jsonl_handler"
_JSONL_PATH_ATTR = "_nullvector_jsonl_path"


class JsonlEventFormatter(logging.Formatter):
    """Serialize structured NullVector events as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "nullvector_event", None)
        if payload is None:
            payload = {
                "message": record.getMessage(),
            }
        return json.dumps(json_safe(payload), sort_keys=True, ensure_ascii=True)


def configure_jsonl_logger(
    path: str,
    *,
    logger: logging.Logger | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Attach a JSONL file handler to the provided logger."""

    configured_logger = logger or logging.getLogger("nullvector")
    destination = Path(path)
    validate_writable_root(str(destination.parent), label="observability event root")
    resolved_destination = str(destination.resolve())
    existing_handlers = [
        handler
        for handler in configured_logger.handlers
        if getattr(handler, _JSONL_HANDLER_ATTR, False)
    ]
    handler: logging.Handler | None = None
    for existing in existing_handlers:
        if getattr(existing, _JSONL_PATH_ATTR, "") == resolved_destination:
            if handler is None:
                handler = existing
                continue
            configured_logger.removeHandler(existing)
            existing.close()
            continue
        configured_logger.removeHandler(existing)
        existing.close()
    if handler is None:
        handler = logging.FileHandler(destination, encoding="utf-8")
        setattr(handler, _JSONL_HANDLER_ATTR, True)
        setattr(handler, _JSONL_PATH_ATTR, resolved_destination)
        configured_logger.addHandler(handler)
    handler.setLevel(level)
    handler.setFormatter(JsonlEventFormatter())
    configured_logger.setLevel(level)
    configured_logger.propagate = False
    return configured_logger


__all__ = ["JsonlEventFormatter", "configure_jsonl_logger"]
