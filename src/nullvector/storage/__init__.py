"""Storage configuration, backends, and shared persistence protocol."""

from nullvector.storage._serialization import (
    build_postgres_artifact_ref,
    build_postgres_binary_ref,
)
from nullvector.storage.artifact_roots import (
    reservation_artifact_root,
    resolve_selection_artifact_root,
    resolve_tree_search_artifact_root,
)
from nullvector.storage.async_postgres import AsyncPostgresDocumentStore
from nullvector.storage.config import (
    FilesystemStorageConfig,
    PostgresStorageConfig,
    StorageBackend,
    StorageConfig,
)
from nullvector.storage.factory import build_document_store
from nullvector.storage.filesystem import FilesystemDocumentStore
from nullvector.storage.postgres import PostgresDependencyError, PostgresDocumentStore
from nullvector.storage.protocol import (
    AsyncDocumentStore,
    AsyncRunScopedStore,
    DocumentStore,
    RunScopedStore,
)

__all__ = [
    "AsyncDocumentStore",
    "AsyncPostgresDocumentStore",
    "AsyncRunScopedStore",
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
    "reservation_artifact_root",
    "resolve_selection_artifact_root",
    "resolve_tree_search_artifact_root",
]
