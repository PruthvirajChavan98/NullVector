"""Contract checks for Phase 1 storage capability helpers."""

from __future__ import annotations

from pathlib import Path

from nullvector.storage.artifact_roots import resolve_tree_search_artifact_root
from nullvector.storage.config import StorageBackend
from nullvector.storage.filesystem import FilesystemDocumentStore
from nullvector.storage.postgres import PostgresDocumentStore


class _FakePostgresStore:
    backend = StorageBackend.POSTGRES

    def resolve_artifact_root(
        self, *, run_type: str, run_id: str, document_id: str, configured_root: str | None = None
    ) -> str | None:
        return None


def test_filesystem_store_reports_capabilities_and_resolves_artifact_roots(
    tmp_path: Path,
) -> None:
    store = FilesystemDocumentStore(str(tmp_path / "artifacts"))

    assert store.supports_metadata_persistence is False
    assert store.supports_retrieval_unit_queries is False
    assert store.resolve_artifact_root(
        run_type="parse",
        run_id="run-001",
        document_id="doc-001",
    ) == str(tmp_path / "artifacts")
    assert store.resolve_artifact_root(
        run_type="parse",
        run_id="run-001",
        document_id="doc-001",
        configured_root="custom/root",
    ) == str(tmp_path / "artifacts" / "custom" / "root")
    explicit_root = tmp_path / "external-root"
    assert store.resolve_artifact_root(
        run_type="parse",
        run_id="run-001",
        document_id="doc-001",
        configured_root=str(explicit_root),
    ) == str(explicit_root)


def test_postgres_store_reports_capabilities_and_hides_run_artifact_root() -> None:
    store = object.__new__(PostgresDocumentStore)

    assert store.supports_metadata_persistence is True
    assert store.supports_retrieval_unit_queries is True
    assert (
        store.resolve_artifact_root(
            run_type="parse",
            run_id="run-001",
            document_id="doc-001",
            configured_root="ignored",
        )
        is None
    )


def test_tree_search_root_preserves_logical_postgres_contract() -> None:
    resolved = resolve_tree_search_artifact_root(
        _FakePostgresStore(),  # type: ignore[arg-type]
        tree_run_id="tree-001",
        search_run_id="search-001",
        configured_root=None,
    )

    assert resolved == "tree-search/tree-001/search-001"


def test_tree_search_root_resolves_relative_to_filesystem_store_root(
    tmp_path: Path,
) -> None:
    store = FilesystemDocumentStore(str(tmp_path / "artifacts"))

    resolved = resolve_tree_search_artifact_root(
        store,
        tree_run_id="tree-002",
        search_run_id="search-002",
        configured_root="custom/search-root",
    )

    assert resolved == str((tmp_path / "artifacts" / "custom" / "search-root").resolve())
