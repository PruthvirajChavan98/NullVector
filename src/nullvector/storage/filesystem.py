"""Filesystem-backed implementation of the shared DocumentStore protocol."""

from __future__ import annotations

import gzip
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from nullvector.domain.common import ScalarValue
from nullvector.domain.document_selection import (
    DocumentFilterClause,
    DocumentMetadataRecord,
)
from nullvector.domain.ledger import DocumentFingerprint
from nullvector.storage._serialization import canonical_json_text
from nullvector.storage.config import StorageBackend
from nullvector.storage.protocol import RunScopedStore, ScopedDocumentRun


class FilesystemDocumentStore:
    """Filesystem persistence that preserves the current artifact layout."""

    backend = StorageBackend.FILESYSTEM

    def __init__(self, root: str) -> None:
        self._root = Path(root)

    @property
    def supports_metadata_persistence(self) -> bool:
        return False

    @property
    def supports_retrieval_unit_queries(self) -> bool:
        return False

    def resolve_artifact_root(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        configured_root: str | None = None,
    ) -> str | None:
        del run_type, run_id, document_id
        if configured_root is None:
            return str(self._root)
        path = Path(configured_root)
        if path.is_absolute():
            return str(path)
        if path == self._root:
            return str(self._root)
        return str(self._path(configured_root))

    def register_document(self, fingerprint: DocumentFingerprint) -> str:
        return fingerprint.document_id

    def reserve_run(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_root: str | None = None,
        identity: Mapping[str, ScalarValue],
    ) -> tuple[bool, dict[str, Any]]:
        if artifact_root is None:
            msg = "FilesystemDocumentStore.reserve_run requires artifact_root"
            raise ValueError(msg)
        run_root = Path(artifact_root).parent
        record_path = run_root / "run-index.json"
        if record_path.exists():
            payload = cast(dict[str, Any], self._read_json_path(record_path))
            return False, payload
        record = {
            "run_type": run_type,
            "run_id": run_id,
            "document_id": document_id,
            "artifact_root": artifact_root,
            "status": "running",
            "identity": dict(identity),
            "manifest_ref": None,
        }
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(canonical_json_text(record, pretty=True), encoding="utf-8")
        return True, record

    def complete_run(
        self,
        *,
        run_type: str,
        run_id: str,
        manifest_ref: str,
        manifest: BaseModel,
    ) -> None:
        manifest_path = Path(manifest_ref)
        candidate_paths = (
            manifest_path.parent.parent / "run-index.json",
            manifest_path.parent / "run-index.json",
        )
        record_path = next((path for path in candidate_paths if path.exists()), candidate_paths[0])
        payload = cast(dict[str, Any], self._read_json_path(record_path))
        completed_payload = {
            **payload,
            "run_type": run_type,
            "run_id": run_id,
            "status": "succeeded",
            "manifest_ref": manifest_ref,
            "manifest": manifest.model_dump(mode="json"),
        }
        record_path.write_text(
            canonical_json_text(completed_payload, pretty=True),
            encoding="utf-8",
        )

    def for_run(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
    ) -> RunScopedStore:
        return ScopedDocumentRun(self, run_type=run_type, run_id=run_id, document_id=document_id)

    def artifact_ref(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_path: str,
    ) -> str:
        del run_type, run_id, document_id
        return str(self._path(artifact_path))

    def binary_asset_ref(
        self,
        *,
        run_id: str,
        document_id: str,
        asset_path: str,
    ) -> str:
        del run_id, document_id
        return str(self._path(asset_path))

    def put_json_artifact(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_kind: str,
        artifact_path: str,
        payload: Any,
    ) -> str:
        del run_type, run_id, document_id, artifact_kind
        destination = self._path(artifact_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix == ".gz":
            with gzip.open(destination, "wt", encoding="utf-8") as handle:
                handle.write(canonical_json_text(payload))
        else:
            destination.write_text(canonical_json_text(payload, pretty=True), encoding="utf-8")
        return str(destination)

    def put_jsonl_artifact(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_kind: str,
        artifact_path: str,
        payloads: Sequence[Any],
    ) -> str:
        del run_type, run_id, document_id, artifact_kind
        destination = self._path(artifact_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            for payload in payloads:
                handle.write(canonical_json_text(payload))
                handle.write("\n")
        return str(destination)

    def put_text_artifact(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_kind: str,
        artifact_path: str,
        content: str,
    ) -> str:
        del run_type, run_id, document_id, artifact_kind
        destination = self._path(artifact_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return str(destination)

    def put_binary_asset(
        self,
        *,
        run_id: str,
        document_id: str,
        asset_path: str,
        content_type: str,
        data: bytes,
    ) -> str:
        del run_id, document_id, content_type
        destination = self._path(asset_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return str(destination)

    def read_json_artifact(self, ref: str) -> Any:
        return self._read_json_path(Path(ref))

    def read_jsonl_artifact(self, ref: str) -> tuple[Any, ...]:
        path = Path(ref)
        return tuple(
            cast(Any, self._read_json_text(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def read_text_artifact(self, ref: str) -> str:
        return Path(ref).read_text(encoding="utf-8")

    def read_binary_asset(self, ref: str) -> bytes:
        return Path(ref).read_bytes()

    def put_retrieval_units(
        self,
        document_id: str,
        units: tuple[BaseModel, ...],
    ) -> int:
        del document_id
        return len(units)

    def query_retrieval_units(
        self,
        document_id: str,
        *,
        page_start: int | None = None,
        page_end: int | None = None,
        unit_types: tuple[str, ...] = (),
        modalities: tuple[str, ...] = (),
        text_query: str | None = None,
        limit: int | None = 50,
    ) -> list[dict[str, Any]]:
        del document_id, page_start, page_end, unit_types, modalities, text_query, limit
        return []

    def put_metadata_records(
        self,
        collection_id: str,
        records: Sequence[DocumentMetadataRecord],
    ) -> int:
        del collection_id
        return len(records)

    def load_metadata_records(self, collection_id: str) -> list[dict[str, Any]]:
        del collection_id
        return []

    def query_metadata_records(
        self,
        collection_id: str,
        *,
        clauses: tuple[DocumentFilterClause, ...] = (),
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        del collection_id, clauses, limit
        return []

    def append_audit(self, record: BaseModel) -> str | None:
        payload = record.model_dump(mode="json")
        destination = self._root / f"{payload['request_id']}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(canonical_json_text(record, pretty=True), encoding="utf-8")
        return str(destination)

    def append_event(self, event: BaseModel) -> None:
        payload = event.model_dump(mode="json")
        destination = self._root / "events" / payload["document_id"] / f"{payload['event_id']}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(canonical_json_text(event, pretty=True), encoding="utf-8")

    def _path(self, artifact_path: str) -> Path:
        path = Path(artifact_path)
        if path.is_absolute():
            return path
        return self._root / path

    def _read_json_path(self, path: Path) -> Any:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return self._read_json_text(handle.read())
        return self._read_json_text(path.read_text(encoding="utf-8"))

    def _read_json_text(self, text: str) -> Any:
        import json

        return cast(Any, json.loads(text))


__all__ = ["FilesystemDocumentStore"]
