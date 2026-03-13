"""Audit helpers for the Phase 03 LLM gateway."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from nullvector.llm.protocols import RedactionHook
from nullvector.llm.types import GatewayAuditRecord, JSONValue


def json_safe(value: Any) -> JSONValue:
    """Convert provider payloads into recursively JSON-safe structures."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if hasattr(value, "dict") and callable(value.dict):
        return json_safe(value.dict())
    if hasattr(value, "__dict__"):
        return json_safe(vars(value))
    return str(value)


def apply_redaction_hooks(
    record: GatewayAuditRecord,
    hooks: tuple[RedactionHook, ...],
) -> GatewayAuditRecord:
    """Apply redaction hooks in order."""

    redacted = record
    for hook in hooks:
        redacted = hook.redact(redacted)
    return redacted


def persist_audit_record(
    record: GatewayAuditRecord,
    *,
    root: str | None,
) -> str | None:
    """Persist a redacted audit record under the configured root when enabled."""

    if root is None:
        return None
    destination = Path(root) / f"{record.request_id}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(json_safe(record), indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    return str(destination)
