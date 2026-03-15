"""Storage configuration, backends, and shared persistence protocol."""

from nullvector.storage._serialization import (
    build_postgres_artifact_ref,
    build_postgres_binary_ref,
)
from nullvector.storage.config import (
    FilesystemStorageConfig,
    PostgresStorageConfig,
    StorageBackend,
    StorageConfig,
)
from nullvector.storage.factory import build_document_store
from nullvector.storage.filesystem import FilesystemDocumentStore
from nullvector.storage.postgres import PostgresDependencyError, PostgresDocumentStore
from nullvector.storage.protocol import DocumentStore, RunScopedStore

__all__ = [
    "DocumentStore",
    "FilesystemDocumentStore",
    "FilesystemStorageConfig",
    "PostgresDependencyError",
    "PostgresDocumentStore",
    "PostgresStorageConfig",
    "RunScopedStore",
    "StorageBackend",
    "StorageConfig",
    "build_document_store",
    "build_postgres_artifact_ref",
    "build_postgres_binary_ref",
]
