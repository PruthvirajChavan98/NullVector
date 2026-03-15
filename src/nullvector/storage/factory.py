"""Internal storage-backend construction helpers."""

from __future__ import annotations

from nullvector.storage.config import (
    FilesystemStorageConfig,
    PostgresStorageConfig,
    StorageConfig,
)
from nullvector.storage.filesystem import FilesystemDocumentStore
from nullvector.storage.postgres import PostgresDocumentStore
from nullvector.storage.protocol import DocumentStore


def build_document_store(
    storage: StorageConfig | None,
    *,
    default_filesystem_root: str,
) -> DocumentStore:
    """Resolve the active DocumentStore from the public storage config surface."""

    if storage is None:
        return FilesystemDocumentStore(default_filesystem_root)
    if isinstance(storage, FilesystemStorageConfig):
        return FilesystemDocumentStore(storage.root or default_filesystem_root)
    if isinstance(storage, PostgresStorageConfig):
        return PostgresDocumentStore(storage.conninfo, schema=storage.pg_schema)
    msg = f"unsupported storage config: {type(storage)!r}"
    raise TypeError(msg)


__all__ = ["build_document_store"]
