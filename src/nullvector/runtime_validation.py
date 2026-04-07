"""Cross-phase artifact and filesystem contract validation helpers."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from nullvector.constants import CERTIFIED_PYMUPDF_VERSIONS, CERTIFIED_PYPDF_VERSIONS
from nullvector.domain.ledger import AcquisitionRunManifest
from nullvector.ingest.errors import ExtractionFailureError
from nullvector.ingest.page_renderer import installed_pymupdf_version

try:
    from pypdf import __version__ as _pypdf_version_str

    def installed_pypdf_version() -> str:
        return _pypdf_version_str

except ImportError:  # pragma: no cover

    def installed_pypdf_version() -> str:
        return "0.0.0"


def validate_writable_root(root: str | None, *, label: str) -> None:
    """Ensure an enabled persistence root is writable before runtime use."""

    del label
    if root is None:
        return
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".write-probe-{uuid4().hex}"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        probe.unlink(missing_ok=True)


def validate_attachment_path(path: str) -> None:
    """Ensure a multimodal attachment path is present and readable."""

    attachment = Path(path)
    if not attachment.exists():
        msg = f"attachment path does not exist: {path}"
        raise ValueError(msg)
    if not attachment.is_file():
        msg = f"attachment path is not a file: {path}"
        raise ValueError(msg)
    if not os.access(attachment, os.R_OK):
        msg = f"attachment path is not readable: {path}"
        raise ValueError(msg)


def validate_pdf_runtime_versions(
    *,
    configured_pymupdf_version: str,
    configured_pypdf_version: str,
    document_id: str = "unknown",
) -> None:
    """Require configured and installed PDF runtimes to match the certified set."""

    if configured_pymupdf_version not in CERTIFIED_PYMUPDF_VERSIONS:
        msg = (
            f"configured PyMuPDF version {configured_pymupdf_version} is not in the certified "
            f"set {CERTIFIED_PYMUPDF_VERSIONS}"
        )
        raise ExtractionFailureError(msg, document_id=document_id)
    if configured_pypdf_version not in CERTIFIED_PYPDF_VERSIONS:
        msg = (
            f"configured pypdf version {configured_pypdf_version} is not in the certified set "
            f"{CERTIFIED_PYPDF_VERSIONS}"
        )
        raise ExtractionFailureError(msg, document_id=document_id)

    pymupdf_version = installed_pymupdf_version()
    pypdf_version = installed_pypdf_version()
    if pymupdf_version not in CERTIFIED_PYMUPDF_VERSIONS:
        msg = (
            f"installed PyMuPDF version {pymupdf_version} is outside the certified set "
            f"{CERTIFIED_PYMUPDF_VERSIONS}"
        )
        raise ExtractionFailureError(msg, document_id=document_id)
    if pypdf_version not in CERTIFIED_PYPDF_VERSIONS:
        msg = (
            f"installed pypdf version {pypdf_version} is outside the certified set "
            f"{CERTIFIED_PYPDF_VERSIONS}"
        )
        raise ExtractionFailureError(msg, document_id=document_id)
    if pymupdf_version != configured_pymupdf_version:
        msg = (
            f"configured PyMuPDF version {configured_pymupdf_version} "
            f"does not match installed {pymupdf_version}"
        )
        raise ExtractionFailureError(msg, document_id=document_id)
    if pypdf_version != configured_pypdf_version:
        msg = (
            f"configured pypdf version {configured_pypdf_version} "
            f"does not match installed {pypdf_version}"
        )
        raise ExtractionFailureError(msg, document_id=document_id)


def validate_canonical_text_substrate_contract(
    *,
    manifest: AcquisitionRunManifest,
) -> str:
    """Require the acquisition manifest to point at a persisted canonical text substrate ref."""

    substrate_path = manifest.canonical_text_substrate_path
    if substrate_path is None:
        msg = "acquisition manifest is missing canonical_text_substrate_path"
        raise ValueError(msg)
    return substrate_path
