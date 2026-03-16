"""Artifact loaders for retrieval manifests and corpora."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.retrieval import RetrievalCorpus, RetrievalManifest
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage._serialization import canonical_json_text, is_postgres_ref


def load_retrieval_manifest(
    path: str | Path,
    *,
    storage: StorageConfig | None = None,
) -> RetrievalManifest:
    """Load a persisted retrieval manifest from JSON."""

    ref = str(path)
    if not is_postgres_ref(ref):
        manifest_path = Path(path)
        return RetrievalManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if storage is None:
        msg = (
            f"load_retrieval_manifest: ref {ref!r} is a PostgreSQL artifact ref "
            "but no storage config was provided; pass storage=<PostgresStorageConfig>"
        )
        raise ValueError(msg)
    store = build_document_store(storage)
    return RetrievalManifest.model_validate_json(canonical_json_text(store.read_json_artifact(ref)))


def load_retrieval_corpus(
    path: str | Path,
    *,
    storage: StorageConfig | None = None,
) -> RetrievalCorpus:
    """Load a persisted retrieval corpus from JSON."""

    ref = str(path)
    if not is_postgres_ref(ref):
        corpus_path = Path(path)
        return RetrievalCorpus.model_validate_json(corpus_path.read_text(encoding="utf-8"))
    if storage is None:
        msg = (
            f"load_retrieval_corpus: ref {ref!r} is a PostgreSQL artifact ref "
            "but no storage config was provided; pass storage=<PostgresStorageConfig>"
        )
        raise ValueError(msg)
    store = build_document_store(storage)
    return RetrievalCorpus.model_validate_json(canonical_json_text(store.read_json_artifact(ref)))


__all__ = [
    "load_retrieval_corpus",
    "load_retrieval_manifest",
]
