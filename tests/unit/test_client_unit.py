"""Unit coverage for the public NullVector client facade."""

from __future__ import annotations

from pathlib import Path

import pytest

import nullvector.client as client_module
from nullvector.client import ClientIngestResult, NullVectorClient
from nullvector.domain.retrieval import (
    DocumentDescriptionManifest,
    RetrievalCorpus,
    RetrievalManifest,
)
from nullvector.domain.tree import TreeBuildManifest
from nullvector.errors import DocumentNotIndexedError
from nullvector.presets import resolve_preset
from nullvector.retrieval.service import RetrievalService
from nullvector.storage import StorageConfig


def test_search_prefers_explicit_manifest_path_over_result_and_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = NullVectorClient(storage_path=tmp_path / "workspace")
    client._update_catalog("doc-123", retrieval_manifest_path="/tmp/from-catalog.json")
    seen: dict[str, str] = {}

    def fake_load_manifest(path: str, *, storage: StorageConfig | None = None) -> RetrievalManifest:
        del storage
        seen["path"] = path
        return RetrievalManifest(
            document_id="doc-123",
            artifact_root="/tmp/retrieval-root",
            corpus_path="/tmp/corpus.json",
            stats_path="/tmp/stats.json",
            unit_count=0,
        )

    def fake_load_corpus(path: str, *, storage: StorageConfig | None = None) -> RetrievalCorpus:
        del path, storage
        return RetrievalCorpus(document_id="doc-123")

    monkeypatch.setattr(client_module, "load_retrieval_manifest", fake_load_manifest)
    monkeypatch.setattr(client_module, "load_retrieval_corpus", fake_load_corpus)
    monkeypatch.setattr(
        RetrievalService,
        "search",
        lambda self, *, corpus, query, limit: (),
    )

    result = client.search(
        "overview",
        retrieval_manifest_path="/tmp/explicit.json",
        ingest_result=ClientIngestResult(
            document_id="doc-123",
            acquisition_manifest_path="/tmp/acquisition.json",
            tree_manifest_path="/tmp/tree.json",
            retrieval_manifest_path="/tmp/from-result.json",
        ),
        document_id="doc-123",
    )

    assert result == ()
    assert seen["path"] == "/tmp/explicit.json"


def test_search_prefers_ingest_result_over_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = NullVectorClient(storage_path=tmp_path / "workspace")
    client._update_catalog("doc-123", retrieval_manifest_path="/tmp/from-catalog.json")
    seen: dict[str, str] = {}

    def fake_load_manifest(path: str, *, storage: StorageConfig | None = None) -> RetrievalManifest:
        del storage
        seen["path"] = path
        return RetrievalManifest(
            document_id="doc-123",
            artifact_root="/tmp/retrieval-root",
            corpus_path="/tmp/corpus.json",
            stats_path="/tmp/stats.json",
            unit_count=0,
        )

    def fake_load_corpus(path: str, *, storage: StorageConfig | None = None) -> RetrievalCorpus:
        del path, storage
        return RetrievalCorpus(document_id="doc-123")

    monkeypatch.setattr(client_module, "load_retrieval_manifest", fake_load_manifest)
    monkeypatch.setattr(client_module, "load_retrieval_corpus", fake_load_corpus)
    monkeypatch.setattr(
        RetrievalService,
        "search",
        lambda self, *, corpus, query, limit: (),
    )

    result = client.search(
        "overview",
        ingest_result=ClientIngestResult(
            document_id="doc-123",
            acquisition_manifest_path="/tmp/acquisition.json",
            tree_manifest_path="/tmp/tree.json",
            retrieval_manifest_path="/tmp/from-result.json",
        ),
        document_id="doc-123",
    )

    assert result == ()
    assert seen["path"] == "/tmp/from-result.json"


def test_search_raises_document_not_indexed_when_catalog_has_no_entry(tmp_path: Path) -> None:
    client = NullVectorClient(storage_path=tmp_path / "workspace")

    with pytest.raises(DocumentNotIndexedError, match="not indexed"):
        client.search("overview", document_id="missing-doc")


def test_build_description_updates_catalog_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = NullVectorClient(storage_path=tmp_path / "workspace")
    client._update_catalog(
        "doc-123",
        acquisition_manifest_path="/tmp/acquisition.json",
        tree_manifest_path="/tmp/tree.json",
    )

    manifest = DocumentDescriptionManifest(
        document_id="doc-123",
        description_run_id="doc-123-description",
        artifact_root="/tmp/description-root",
        description_path="/tmp/description.json",
        source_tree_manifest_path="/tmp/tree.json",
        source_acquisition_manifest_path="/tmp/acquisition.json",
    )

    monkeypatch.setattr(
        client_module,
        "load_model_artifact",
        lambda model_type, path, *, storage=None: TreeBuildManifest(
            tree_run_id="doc-123-tree",
            document_id="doc-123",
            registry_root="/tmp/tree",
            acquisition_manifest_path="/tmp/acquisition.json",
            acquisition_artifact_identity="/tmp/acquisition.json",
            acquisition_fingerprint_sha256="0" * 64,
            artifact_root="/tmp/tree-root",
            settings=resolve_preset("general_document").tree_settings,
            settings_digest="1" * 64,
            committed_node_count=1,
            unassigned_span_count=0,
        ),
    )

    class StubBuilder:
        def __init__(self, *, logger: object = None, storage: object = None) -> None:
            del logger, storage

        def build(
            self,
            request: object,
            *,
            gateway: object = None,
        ) -> DocumentDescriptionManifest:
            del request, gateway
            return manifest

    monkeypatch.setattr(client_module, "DocumentDescriptionBuilder", StubBuilder)

    built = client.build_description(
        "/tmp/acquisition.json",
        "/tmp/tree.json",
        preset="general_document",
    )

    assert built == manifest
    catalog = client._load_catalog()
    assert (
        catalog.documents["doc-123"].description_manifest_path
        == "/tmp/description-root/manifest.json"
    )
