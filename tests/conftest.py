"""Root-level test fixtures shared across all test sub-packages."""

from __future__ import annotations

from pathlib import Path

import pytest

from nullvector.domain.ledger import DocumentFingerprint
from nullvector.storage.filesystem import FilesystemDocumentStore


@pytest.fixture()
def document_store(tmp_path: Path) -> FilesystemDocumentStore:
    """Create a FilesystemDocumentStore rooted under a temporary directory."""
    return FilesystemDocumentStore(str(tmp_path / "artifacts" / "run" / "doc"))


@pytest.fixture()
def dummy_fingerprint() -> DocumentFingerprint:
    """Return a deterministic DocumentFingerprint suitable for unit tests."""
    return DocumentFingerprint(
        document_id="d" * 64,
        source_path="/tmp/example.pdf",
        sha256="a" * 64,
        file_size_bytes=123,
        page_count=4,
    )
