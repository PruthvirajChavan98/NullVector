"""Shared artifact-root helpers for collection-scoped selection services."""

from __future__ import annotations

from pathlib import Path

from nullvector.storage import StorageConfig
from nullvector.storage.config import FilesystemStorageConfig, PostgresStorageConfig


def selection_artifact_root(
    *,
    collection_id: str,
    selection_run_id: str,
    artifact_root: str | None,
    storage: StorageConfig | None,
) -> str:
    """Resolve the stable artifact root for one collection-selection run."""

    if isinstance(storage, PostgresStorageConfig):
        return artifact_root or f"document-selection/{collection_id}/{selection_run_id}"

    base_root = (
        Path(storage.root)
        if isinstance(storage, FilesystemStorageConfig) and storage.root is not None
        else Path()
    )
    configured_root = Path(
        artifact_root or str(Path("document-selection") / collection_id / selection_run_id)
    )
    if not configured_root.is_absolute():
        configured_root = (base_root / configured_root).resolve()
    return str(configured_root)


def selection_artifact_path(artifact_root: str, filename: str) -> str:
    """Return the path for one persisted selection artifact."""

    return str(Path(artifact_root) / filename)


__all__ = ["selection_artifact_path", "selection_artifact_root"]
