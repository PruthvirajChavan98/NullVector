"""Filesystem-backed artifact persistence for parse runs."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from nullvector.domain.models import ParserSettings, ParseRunIndex, ParseRunManifest


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


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JSON-serializable value deterministically."""

    return json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def settings_digest(settings: ParserSettings) -> str:
    """Hash effective parser settings for idempotency."""

    return hashlib.sha256(canonical_json_bytes(settings)).hexdigest()


class ArtifactStore:
    """Repository-local artifact writer for deterministic parse runs."""

    def __init__(self, artifact_root: str, parse_run_id: str, document_id: str) -> None:
        self.parse_run_path = Path(artifact_root) / parse_run_id
        self.base_path = self.parse_run_path / document_id

    def ensure(self) -> None:
        self.parse_run_path.mkdir(parents=True, exist_ok=True)
        for relative in (
            Path("source"),
            Path("outline"),
            Path("ledger"),
            Path("pages"),
        ):
            (self.base_path / relative).mkdir(parents=True, exist_ok=True)

    def relative(self, *parts: str) -> str:
        return str(Path(*parts))

    def absolute(self, *parts: str) -> Path:
        return self.base_path / Path(*parts)

    def copy_source(self, source_path: str) -> str:
        destination = self.absolute("source", "original.pdf")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)
        return str(destination)

    def write_json(self, relative_path: str, payload: Any) -> str:
        destination = self.absolute(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True).encode(
                "utf-8"
            ),
        )
        return str(destination)

    def write_json_gz(self, relative_path: str, payload: Any) -> str:
        destination = self.absolute(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(destination, "wt", encoding="utf-8") as handle:
            json.dump(_json_safe(payload), handle, sort_keys=True)
        return str(destination)

    def write_text(self, relative_path: str, content: str) -> str:
        destination = self.absolute(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return str(destination)

    def write_bytes(self, relative_path: str, content: bytes) -> str:
        destination = self.absolute(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return str(destination)

    def write_ledger(self, relative_path: str, rows: Sequence[BaseModel]) -> str:
        destination = self.absolute(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(row.model_dump_json())
                handle.write("\n")
        return str(destination)

    def write_manifest(self, manifest: ParseRunManifest) -> str:
        return self.write_json("manifest.json", manifest)

    def load_manifest(self) -> ParseRunManifest | None:
        path = self.absolute("manifest.json")
        if not path.exists():
            return None
        return ParseRunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def write_run_index(self, run_index: ParseRunIndex) -> str:
        destination = self.parse_run_path / "run-index.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            json.dumps(_json_safe(run_index), indent=2, sort_keys=True, ensure_ascii=True).encode(
                "utf-8"
            ),
        )
        return str(destination)

    def load_run_index(self) -> ParseRunIndex | None:
        path = self.parse_run_path / "run-index.json"
        if not path.exists():
            return None
        return ParseRunIndex.model_validate_json(path.read_text(encoding="utf-8"))

    def load_manifest_at(self, manifest_path: str) -> ParseRunManifest | None:
        path = Path(manifest_path)
        if not path.exists():
            return None
        return ParseRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
