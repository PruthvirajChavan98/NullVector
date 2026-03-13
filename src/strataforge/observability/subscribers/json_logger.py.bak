"""JSONL event subscriber."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from strataforge.observability.events import FrameworkEvent
from strataforge.runtime_validation import validate_writable_root


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


class JsonLoggerSubscriber:
    """Append-only JSONL subscriber for structured runtime events."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        validate_writable_root(str(self._path.parent), label="observability event root")

    def handle(self, event: FrameworkEvent) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_json_safe(event), sort_keys=True, ensure_ascii=True))
            handle.write("\n")


__all__ = ["JsonLoggerSubscriber"]
