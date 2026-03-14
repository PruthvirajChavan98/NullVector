"""Artifact loaders for retrieval manifests and corpora."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.retrieval import RetrievalCorpus, RetrievalManifest


def load_retrieval_manifest(path: str | Path) -> RetrievalManifest:
    """Load a persisted retrieval manifest from JSON."""

    manifest_path = Path(path)
    return RetrievalManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))


def load_retrieval_corpus(path: str | Path) -> RetrievalCorpus:
    """Load a persisted retrieval corpus from JSON."""

    corpus_path = Path(path)
    return RetrievalCorpus.model_validate_json(corpus_path.read_text(encoding="utf-8"))


__all__ = [
    "load_retrieval_corpus",
    "load_retrieval_manifest",
]
