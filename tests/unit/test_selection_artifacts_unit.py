"""Unit coverage for shared selection artifact helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from nullvector.retrieval._selection_artifacts import (
    selection_artifact_path,
    selection_artifact_root,
)
from nullvector.storage.config import StorageBackend
from nullvector.storage.filesystem import FilesystemDocumentStore


class _FakePostgresStore:
    backend = StorageBackend.POSTGRES

    def resolve_artifact_root(
        self, *, run_type: str, run_id: str, document_id: str, configured_root: str | None = None
    ) -> str | None:
        return None


def test_selection_artifact_root_returns_explicit_postgres_artifact_root() -> None:
    explicit_root = "pg://document_selection/selection-001/explicit-root"

    resolved = selection_artifact_root(
        collection_id="collection-alpha",
        selection_run_id="selection-001",
        artifact_root=explicit_root,
        store=_FakePostgresStore(),  # type: ignore[arg-type]
    )

    assert resolved == explicit_root


def test_selection_artifact_root_builds_default_postgres_artifact_root() -> None:
    resolved = selection_artifact_root(
        collection_id="collection-alpha",
        selection_run_id="selection-002",
        artifact_root=None,
        store=_FakePostgresStore(),  # type: ignore[arg-type]
    )

    assert resolved == "document-selection/collection-alpha/selection-002"


def test_selection_artifact_root_resolves_relative_to_filesystem_storage_root(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "artifacts"

    resolved = selection_artifact_root(
        collection_id="collection-beta",
        selection_run_id="selection-003",
        artifact_root="custom/root",
        store=FilesystemDocumentStore(str(storage_root)),
    )

    assert resolved == str((storage_root / "custom" / "root").resolve())


def test_selection_artifact_root_resolves_relative_to_cwd_without_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    resolved = selection_artifact_root(
        collection_id="collection-gamma",
        selection_run_id="selection-004",
        artifact_root=None,
        store=FilesystemDocumentStore("."),
    )

    assert resolved == str(
        (tmp_path / "document-selection" / "collection-gamma" / "selection-004").resolve()
    )


def test_selection_artifact_path_joins_filename_to_root() -> None:
    artifact_root = "/tmp/document-selection/collection-delta/selection-005"

    resolved = selection_artifact_path(artifact_root, "metadata-selection-results.json")

    assert resolved == str(Path(artifact_root) / "metadata-selection-results.json")
