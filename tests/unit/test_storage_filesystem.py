"""Unit coverage for the filesystem document store backend."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.ledger import DocumentFingerprint
from nullvector.storage.filesystem import FilesystemDocumentStore


def _fingerprint() -> DocumentFingerprint:
    return DocumentFingerprint(
        document_id="d" * 64,
        source_path="/tmp/example.pdf",
        sha256="a" * 64,
        file_size_bytes=123,
        page_count=4,
    )


def test_filesystem_store_reserves_runs_and_round_trips_artifacts(tmp_path: Path) -> None:
    store = FilesystemDocumentStore(str(tmp_path / "artifacts" / "run-001" / "doc-001"))
    document_id = store.register_document(_fingerprint())

    created, run_record = store.reserve_run(
        run_type="parse",
        run_id="run-001",
        document_id=document_id,
        artifact_root=str(tmp_path / "artifacts" / "run-001" / "doc-001"),
        identity={
            "document_id": document_id,
            "fingerprint_sha256": "a" * 64,
            "settings_digest": "b" * 64,
        },
    )

    assert created is True
    assert run_record["status"] == "running"

    json_ref = store.put_json_artifact(
        run_type="parse",
        run_id="run-001",
        document_id=document_id,
        artifact_kind="manifest",
        artifact_path="manifest.json",
        payload={"hello": "world"},
    )
    text_ref = store.put_text_artifact(
        run_type="parse",
        run_id="run-001",
        document_id=document_id,
        artifact_kind="text",
        artifact_path="pages/000000/native.txt",
        content="native text",
    )
    binary_ref = store.put_binary_asset(
        run_id="run-001",
        document_id=document_id,
        asset_path="pages/000000/render.png",
        content_type="image/png",
        data=b"png-bytes",
    )

    assert store.read_json_artifact(json_ref) == {"hello": "world"}
    assert store.read_text_artifact(text_ref) == "native text"
    assert store.read_binary_asset(binary_ref) == b"png-bytes"


def test_filesystem_store_scopes_refs_and_writes_to_one_run(tmp_path: Path) -> None:
    store = FilesystemDocumentStore(str(tmp_path / "artifacts" / "run-003" / "doc-003"))
    document_id = store.register_document(_fingerprint())
    artifact_root = str(tmp_path / "artifacts" / "run-003" / "doc-003")
    store.reserve_run(
        run_type="acquisition",
        run_id="run-003",
        document_id=document_id,
        artifact_root=artifact_root,
        identity={
            "document_id": document_id,
            "fingerprint_sha256": "a" * 64,
            "settings_digest": "b" * 64,
        },
    )
    run_store = store.for_run(
        run_type="acquisition",
        run_id="run-003",
        document_id=document_id,
    )

    manifest_ref = run_store.artifact_ref("manifest.json")
    text_ref = run_store.artifact_ref("projection/tree-synthesis-view.json")
    binary_ref = run_store.binary_ref("assets/pages/000000/render-144dpi.png")

    assert manifest_ref == str(tmp_path / "artifacts" / "run-003" / "doc-003" / "manifest.json")
    assert text_ref == str(
        tmp_path / "artifacts" / "run-003" / "doc-003" / "projection" / "tree-synthesis-view.json"
    )
    assert binary_ref == str(
        tmp_path
        / "artifacts"
        / "run-003"
        / "doc-003"
        / "assets"
        / "pages"
        / "000000"
        / "render-144dpi.png"
    )

    assert (
        run_store.put_json(
            artifact_kind="manifest",
            artifact_path="manifest.json",
            payload={"ok": True},
        )
        == manifest_ref
    )
    assert (
        run_store.put_text(
            artifact_kind="projection",
            artifact_path="projection/tree-synthesis-view.json",
            content="projection",
        )
        == text_ref
    )
    assert (
        run_store.put_binary(
            asset_path="assets/pages/000000/render-144dpi.png",
            content_type="image/png",
            data=b"png",
        )
        == binary_ref
    )


def test_filesystem_store_writes_run_index_on_complete(tmp_path: Path) -> None:
    store = FilesystemDocumentStore(str(tmp_path / "artifacts" / "run-002" / "doc-002"))
    document_id = store.register_document(_fingerprint())
    artifact_root = str(tmp_path / "artifacts" / "run-002" / "doc-002")
    store.reserve_run(
        run_type="parse",
        run_id="run-002",
        document_id=document_id,
        artifact_root=artifact_root,
        identity={
            "document_id": document_id,
            "fingerprint_sha256": "a" * 64,
            "settings_digest": "b" * 64,
        },
    )
    manifest_ref = store.put_json_artifact(
        run_type="parse",
        run_id="run-002",
        document_id=document_id,
        artifact_kind="manifest",
        artifact_path="manifest.json",
        payload={"status": "ok"},
    )

    class _Manifest:
        def model_dump(self, mode: str = "json") -> dict[str, str]:
            del mode
            return {"status": "ok"}

    store.complete_run(
        run_type="parse",
        run_id="run-002",
        manifest_ref=manifest_ref,
        manifest=_Manifest(),  # type: ignore[arg-type]
    )

    run_index = (tmp_path / "artifacts" / "run-002" / "run-index.json").read_text(encoding="utf-8")

    assert '"run_id": "run-002"' in run_index
    assert '"run_type": "parse"' in run_index
    assert '"status": "succeeded"' in run_index
