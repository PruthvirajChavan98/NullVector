"""Shared artifact-path helpers for collection-scoped selection services."""

from __future__ import annotations

from pathlib import Path

from nullvector.storage.artifact_roots import resolve_selection_artifact_root
from nullvector.storage.protocol import DocumentStore


def selection_artifact_root(
    *,
    collection_id: str,
    selection_run_id: str,
    artifact_root: str | None,
    store: DocumentStore,
) -> str:
    """Resolve the stable artifact root for one collection-selection run."""

    return resolve_selection_artifact_root(
        store,
        collection_id=collection_id,
        selection_run_id=selection_run_id,
        configured_root=artifact_root,
    )


def selection_artifact_path(artifact_root: str, filename: str) -> str:
    """Return the path for one persisted selection artifact."""

    return str(Path(artifact_root) / filename)


__all__ = ["selection_artifact_path", "selection_artifact_root"]
