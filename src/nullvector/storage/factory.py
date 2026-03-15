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
    default_filesystem_root: str | None = None,
) -> DocumentStore:
    """Resolve the active DocumentStore from the public storage config surface.

    Args:
        storage: The storage config to resolve. None defaults to filesystem.
        default_filesystem_root: Required only for filesystem backends. If the
            resolved backend is filesystem and no root is available from either
            the config or this argument, raises ValueError.

    Returns:
        A DocumentStore implementation for the resolved backend.

    Raises:
        ValueError: If the filesystem backend is selected but no root path is provided.
        TypeError: If the storage config type is not recognised.
    """
    if storage is None or isinstance(storage, FilesystemStorageConfig):
        resolved_root = (
            storage.root if isinstance(storage, FilesystemStorageConfig) else None
        ) or default_filesystem_root
        if resolved_root is None:
            msg = (
                "FilesystemDocumentStore requires a root path; "
                "provide default_filesystem_root or set storage.root"
            )
            raise ValueError(msg)
        return FilesystemDocumentStore(resolved_root)
    if isinstance(storage, PostgresStorageConfig):
        return PostgresDocumentStore(storage.conninfo, schema=storage.pg_schema)
    msg = f"unsupported storage config: {type(storage)!r}"
    raise TypeError(msg)


__all__ = ["build_document_store"]
