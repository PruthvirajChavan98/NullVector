"""The single persistence boundary shared across NullVector runtimes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from nullvector.domain.common import ScalarValue
from nullvector.domain.ledger import DocumentFingerprint
from nullvector.storage.config import StorageBackend


class RunScopedStore(Protocol):
    """One persistence handle scoped to a single reserved run."""

    backend: StorageBackend
    run_type: str
    run_id: str
    document_id: str

    def artifact_ref(self, artifact_path: str) -> str:
        """Return the deterministic ref for one artifact path."""

    def binary_ref(self, asset_path: str) -> str:
        """Return the deterministic ref for one binary asset path."""

    def put_json(
        self,
        *,
        artifact_kind: str,
        artifact_path: str,
        payload: Any,
    ) -> str:
        """Persist one JSON artifact and return its stable ref."""

    def put_jsonl(
        self,
        *,
        artifact_kind: str,
        artifact_path: str,
        payloads: Sequence[Any],
    ) -> str:
        """Persist one JSONL artifact and return its stable ref."""

    def put_text(
        self,
        *,
        artifact_kind: str,
        artifact_path: str,
        content: str,
    ) -> str:
        """Persist one UTF-8 text artifact and return its stable ref."""

    def put_binary(
        self,
        *,
        asset_path: str,
        content_type: str,
        data: bytes,
    ) -> str:
        """Persist one binary asset and return its stable ref."""

    def complete(
        self,
        *,
        manifest_ref: str,
        manifest: BaseModel,
    ) -> None:
        """Mark the scoped run as complete."""


class DocumentStore(Protocol):
    """Read/write boundary for NullVector persistence backends."""

    backend: StorageBackend

    def register_document(self, fingerprint: DocumentFingerprint) -> str:
        """Upsert one document fingerprint and return its document id."""

    def reserve_run(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_root: str | None = None,
        identity: Mapping[str, ScalarValue],
    ) -> tuple[bool, dict[str, Any]]:
        """Atomically reserve one run id or return the existing run record."""

    def complete_run(
        self,
        *,
        run_type: str,
        run_id: str,
        manifest_ref: str,
        manifest: BaseModel,
    ) -> None:
        """Mark a run as succeeded and persist its manifest payload."""

    def for_run(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
    ) -> RunScopedStore:
        """Return a scoped handle for one reserved run."""

    def artifact_ref(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_path: str,
    ) -> str:
        """Return the deterministic ref for one artifact path."""

    def binary_asset_ref(
        self,
        *,
        run_id: str,
        document_id: str,
        asset_path: str,
    ) -> str:
        """Return the deterministic ref for one binary asset path."""

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
        """Persist one JSON artifact and return its stable reference."""

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
        """Persist one JSONL artifact and return its stable reference."""

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
        """Persist one UTF-8 text artifact and return its stable reference."""

    def put_binary_asset(
        self,
        *,
        run_id: str,
        document_id: str,
        asset_path: str,
        content_type: str,
        data: bytes,
    ) -> str:
        """Persist one binary asset and return its stable reference."""

    def read_json_artifact(self, ref: str) -> Any:
        """Load one JSON artifact payload by ref."""

    def read_jsonl_artifact(self, ref: str) -> tuple[Any, ...]:
        """Load one JSONL artifact payload by ref."""

    def read_text_artifact(self, ref: str) -> str:
        """Load one UTF-8 text artifact by ref."""

    def read_binary_asset(self, ref: str) -> bytes:
        """Load one binary asset by ref."""

    def put_retrieval_units(
        self,
        document_id: str,
        units: tuple[BaseModel, ...],
    ) -> int:
        """Bulk persist retrieval units when the backend supports it."""

    def query_retrieval_units(
        self,
        document_id: str,
        *,
        page_start: int | None = None,
        page_end: int | None = None,
        unit_types: tuple[str, ...] = (),
        modalities: tuple[str, ...] = (),
        text_query: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Filter persisted retrieval units when the backend supports it."""

    def append_audit(self, record: BaseModel) -> str | None:
        """Persist one audit record and return its reference when enabled."""

    def append_event(self, event: BaseModel) -> None:
        """Persist one append-only structured event."""


@dataclass(frozen=True)
class ScopedDocumentRun:
    """Generic run-scoped wrapper shared by filesystem and PostgreSQL stores."""

    store: DocumentStore
    run_type: str
    run_id: str
    document_id: str

    @property
    def backend(self) -> StorageBackend:
        return self.store.backend

    def artifact_ref(self, artifact_path: str) -> str:
        return self.store.artifact_ref(
            run_type=self.run_type,
            run_id=self.run_id,
            document_id=self.document_id,
            artifact_path=artifact_path,
        )

    def binary_ref(self, asset_path: str) -> str:
        return self.store.binary_asset_ref(
            run_id=self.run_id,
            document_id=self.document_id,
            asset_path=asset_path,
        )

    def put_json(
        self,
        *,
        artifact_kind: str,
        artifact_path: str,
        payload: Any,
    ) -> str:
        return self.store.put_json_artifact(
            run_type=self.run_type,
            run_id=self.run_id,
            document_id=self.document_id,
            artifact_kind=artifact_kind,
            artifact_path=artifact_path,
            payload=payload,
        )

    def put_jsonl(
        self,
        *,
        artifact_kind: str,
        artifact_path: str,
        payloads: Sequence[Any],
    ) -> str:
        return self.store.put_jsonl_artifact(
            run_type=self.run_type,
            run_id=self.run_id,
            document_id=self.document_id,
            artifact_kind=artifact_kind,
            artifact_path=artifact_path,
            payloads=payloads,
        )

    def put_text(
        self,
        *,
        artifact_kind: str,
        artifact_path: str,
        content: str,
    ) -> str:
        return self.store.put_text_artifact(
            run_type=self.run_type,
            run_id=self.run_id,
            document_id=self.document_id,
            artifact_kind=artifact_kind,
            artifact_path=artifact_path,
            content=content,
        )

    def put_binary(
        self,
        *,
        asset_path: str,
        content_type: str,
        data: bytes,
    ) -> str:
        return self.store.put_binary_asset(
            run_id=self.run_id,
            document_id=self.document_id,
            asset_path=asset_path,
            content_type=content_type,
            data=data,
        )

    def complete(
        self,
        *,
        manifest_ref: str,
        manifest: BaseModel,
    ) -> None:
        self.store.complete_run(
            run_type=self.run_type,
            run_id=self.run_id,
            manifest_ref=manifest_ref,
            manifest=manifest,
        )


__all__ = ["DocumentStore", "RunScopedStore", "ScopedDocumentRun"]
