"""Shared storage serialization, identity, and artifact-reference helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from pydantic import BaseModel

from nullvector.domain.common import ScalarValue

_POSTGRES_ARTIFACT_SCHEME = "pg"
_POSTGRES_BINARY_PREFIX = "__binary__"
_IDENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "fingerprint_sha256": (
        "source_fingerprint_sha256",
        "acquisition_fingerprint_sha256",
    ),
}


def json_safe(value: Any) -> Any:
    """Convert mixed runtime values into stable JSON-safe data."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return json_safe(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if hasattr(value, "dict") and callable(value.dict):
        return json_safe(value.dict())
    if hasattr(value, "__dict__"):
        return json_safe(vars(value))
    return str(value)


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JSON-serializable value deterministically."""

    return json.dumps(
        json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def canonical_json_text(value: Any, *, pretty: bool = False) -> str:
    """Encode JSON-safe payloads using NullVector's canonical rules."""

    indent = 2 if pretty else None
    separators = None if pretty else (",", ":")
    return json.dumps(
        json_safe(value),
        indent=indent,
        sort_keys=True,
        separators=separators,
        ensure_ascii=True,
    )


def settings_digest(settings: Any) -> str:
    """Hash deterministic settings payloads for idempotency."""

    return hashlib.sha256(canonical_json_bytes(settings)).hexdigest()


def run_identity_matches(
    payload: Mapping[str, Any],
    expected_identity: Mapping[str, ScalarValue],
    *,
    aliases: Mapping[str, tuple[str, ...]] | None = None,
) -> bool:
    """Compare one stored run record against canonical expected identity fields."""

    merged_aliases = dict(_IDENTITY_ALIASES)
    if aliases is not None:
        merged_aliases.update(aliases)
    identity = payload.get("identity", {})
    identity_mapping = identity if isinstance(identity, Mapping) else {}
    for key, expected_value in expected_identity.items():
        actual = _payload_identity_value(
            payload,
            identity_mapping,
            key,
            aliases=merged_aliases.get(key, ()),
        )
        if actual != expected_value:
            return False
    return True


def write_json_file(path: Path, payload: Any) -> str:
    """Write a stable UTF-8 JSON artifact and return the path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json_text(payload, pretty=True), encoding="utf-8")
    return str(path)


def build_postgres_artifact_ref(
    *,
    run_type: str,
    run_id: str,
    document_id: str,
    artifact_path: str,
) -> str:
    """Build a stable PostgreSQL artifact reference URI."""

    encoded_path = quote(artifact_path.lstrip("/"), safe="/._-")
    return f"{_POSTGRES_ARTIFACT_SCHEME}://{run_type}/{run_id}/{document_id}/{encoded_path}"


def build_postgres_binary_ref(
    *,
    run_id: str,
    document_id: str,
    asset_path: str,
) -> str:
    """Build a stable PostgreSQL binary-asset reference URI."""

    encoded_path = quote(asset_path.lstrip("/"), safe="/._-")
    return (
        f"{_POSTGRES_ARTIFACT_SCHEME}://{_POSTGRES_BINARY_PREFIX}/{run_id}/"
        f"{document_id}/{encoded_path}"
    )


def is_postgres_ref(ref: str) -> bool:
    """Return whether a stored artifact ref targets the PostgreSQL backend."""

    return ref.startswith(f"{_POSTGRES_ARTIFACT_SCHEME}://")


def parse_postgres_ref(ref: str) -> tuple[str, str, str, str]:
    """Parse a PostgreSQL artifact or binary reference into its path components."""

    prefix = f"{_POSTGRES_ARTIFACT_SCHEME}://"
    if not ref.startswith(prefix):
        msg = f"not a PostgreSQL artifact ref: {ref}"
        raise ValueError(msg)
    segments = ref[len(prefix) :].split("/", 3)
    if len(segments) != 4:
        msg = f"invalid PostgreSQL artifact ref: {ref}"
        raise ValueError(msg)
    first, second, third, fourth = segments
    return first, second, third, unquote(fourth)


def _payload_identity_value(
    payload: Mapping[str, Any],
    identity: Mapping[str, Any],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
) -> Any:
    candidate_keys = (key, *aliases)
    for candidate in candidate_keys:
        if candidate in payload:
            return payload[candidate]
    for candidate in candidate_keys:
        if candidate in identity:
            return identity[candidate]
    return None


__all__ = [
    "build_postgres_artifact_ref",
    "build_postgres_binary_ref",
    "canonical_json_bytes",
    "canonical_json_text",
    "is_postgres_ref",
    "json_safe",
    "parse_postgres_ref",
    "run_identity_matches",
    "settings_digest",
    "write_json_file",
]
