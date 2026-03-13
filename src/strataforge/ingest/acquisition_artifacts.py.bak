"""Filesystem-backed artifact persistence for v2 acquisition runs."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from strataforge.domain.models import (
    AcquisitionRunIndex,
    AcquisitionRunManifest,
    AcquisitionSettings,
)
from strataforge.ingest.artifacts import canonical_json_bytes


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


def settings_digest(settings: AcquisitionSettings) -> str:
    """Hash effective acquisition settings for idempotency."""

    return hashlib.sha256(canonical_json_bytes(settings)).hexdigest()


class AcquisitionArtifactStore:
    """Repository-local artifact writer for deterministic acquisition runs."""

    def __init__(self, artifact_root: str, acquisition_run_id: str, document_id: str) -> None:
        self.run_path = Path(artifact_root) / acquisition_run_id
        self.base_path = self.run_path / document_id

    def ensure(self) -> None:
        self.run_path.mkdir(parents=True, exist_ok=True)
        for relative in (
            Path("source"),
            Path("ledger"),
            Path("outline"),
            Path("events"),
            Path("projection"),
        ):
            (self.base_path / relative).mkdir(parents=True, exist_ok=True)

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
        destination.write_text(
            json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
        return str(destination)

    def write_jsonl(self, relative_path: str, payloads: Sequence[Any]) -> str:
        destination = self.absolute(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            for payload in payloads:
                handle.write(
                    json.dumps(_json_safe(payload), sort_keys=True, ensure_ascii=True),
                )
                handle.write("\n")
        return str(destination)

    def write_bytes(self, relative_path: str, content: bytes) -> str:
        destination = self.absolute(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return str(destination)

    def write_manifest(self, manifest: AcquisitionRunManifest) -> str:
        return self.write_json("manifest.json", manifest)

    def load_manifest(self) -> AcquisitionRunManifest | None:
        path = self.absolute("manifest.json")
        if not path.exists():
            return None
        return AcquisitionRunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def write_run_index(self, run_index: AcquisitionRunIndex) -> str:
        destination = self.run_path / "run-index.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(_json_safe(run_index), indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
        return str(destination)

    def load_run_index(self) -> AcquisitionRunIndex | None:
        path = self.run_path / "run-index.json"
        if not path.exists():
            return None
        return AcquisitionRunIndex.model_validate_json(path.read_text(encoding="utf-8"))

    def load_manifest_at(self, manifest_path: str) -> AcquisitionRunManifest | None:
        path = Path(manifest_path)
        if not path.exists():
            return None
        return AcquisitionRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
