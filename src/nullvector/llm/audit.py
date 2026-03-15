"""Audit helpers for the Phase 03 LLM gateway."""

from __future__ import annotations

import json
from pathlib import Path

from nullvector.llm.protocols import RedactionHook
from nullvector.llm.types import GatewayAuditRecord
from nullvector.storage._serialization import json_safe as json_safe


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


__all__ = [
    "apply_redaction_hooks",
    "json_safe",
    "persist_audit_record",
]
