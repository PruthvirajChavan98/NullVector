"""Storage-owned artifact-root resolution helpers."""

from __future__ import annotations

from pathlib import Path

from nullvector.storage.protocol import DocumentStore


def resolve_selection_artifact_root(
    store: DocumentStore,
    *,
    collection_id: str,
    selection_run_id: str,
    configured_root: str | None = None,
) -> str:
    """Resolve the artifact root for one collection-scoped selection run."""

    logical_key = configured_root or f"document-selection/{collection_id}/{selection_run_id}"
    resolved = store.resolve_artifact_root(
        run_type="document_selection",
        run_id=selection_run_id,
        document_id=collection_id,
        configured_root=configured_root
        or str(Path("document-selection") / collection_id / selection_run_id),
    )
    if resolved is None:
        return logical_key
    path = Path(resolved)
    return str(path if path.is_absolute() else path.resolve())


def resolve_tree_search_artifact_root(
    store: DocumentStore,
    *,
    tree_run_id: str,
    search_run_id: str,
    configured_root: str | None = None,
) -> str:
    """Resolve the artifact root for one tree-search run."""

    logical_key = configured_root or f"tree-search/{tree_run_id}/{search_run_id}"
    resolved = store.resolve_artifact_root(
        run_type="tree_search",
        run_id=search_run_id,
        document_id=tree_run_id,
        configured_root=configured_root or str(Path("tree-search") / tree_run_id / search_run_id),
    )
    if resolved is None:
        return logical_key
    path = Path(resolved)
    return str(path if path.is_absolute() else path.resolve())


__all__ = [
    "reservation_artifact_root",
    "resolve_selection_artifact_root",
    "resolve_tree_search_artifact_root",
]


def reservation_artifact_root(
    artifact_root: str | None,
    *,
    marker_name: str = ".run",
) -> str | None:
    """Return the internal filesystem run-root used for generic run markers."""

    if artifact_root is None:
        return None
    return str(Path(artifact_root) / marker_name)
