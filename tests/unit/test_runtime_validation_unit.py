"""Unit tests for runtime validation helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from nullvector.constants import EXPECTED_PYMUPDF_VERSION, EXPECTED_PYPDF_VERSION
from nullvector.ingest.errors import ExtractionFailureError
from nullvector.runtime_validation import (
    validate_pdf_runtime_versions,
    validate_writable_root,
)


def test_validate_writable_root_supports_concurrent_probes(tmp_path: Path) -> None:
    root = tmp_path / "observability"

    def _probe() -> None:
        validate_writable_root(str(root), label="concurrent root")

    with ThreadPoolExecutor(max_workers=8) as executor:
        for future in tuple(executor.submit(_probe) for _ in range(32)):
            future.result()

    assert root.exists()
    assert tuple(root.glob(".write-probe*")) == ()


def test_validate_pdf_runtime_versions_accepts_certified_versions() -> None:
    validate_pdf_runtime_versions(
        configured_pymupdf_version=EXPECTED_PYMUPDF_VERSION,
        configured_pypdf_version=EXPECTED_PYPDF_VERSION,
    )


def test_validate_pdf_runtime_versions_rejects_uncertified_pymupdf() -> None:
    with pytest.raises(ExtractionFailureError, match="configured PyMuPDF version"):
        validate_pdf_runtime_versions(
            configured_pymupdf_version="0.0.0",
            configured_pypdf_version=EXPECTED_PYPDF_VERSION,
        )


def test_validate_pdf_runtime_versions_rejects_uncertified_pypdf() -> None:
    with pytest.raises(ExtractionFailureError, match="configured pypdf version"):
        validate_pdf_runtime_versions(
            configured_pymupdf_version=EXPECTED_PYMUPDF_VERSION,
            configured_pypdf_version="0.0.0",
        )
