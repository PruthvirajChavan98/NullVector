"""Cross-phase artifact and filesystem contract validation helpers."""

from __future__ import annotations

import os
from pathlib import Path

from nullvector.domain.models import AcquisitionRunManifest


def validate_writable_root(root: str | None, *, label: str) -> None:
    """Ensure an enabled persistence root is writable before runtime use."""

    if root is None:
        return
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        if probe.exists():
            probe.unlink()


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


def validate_canonical_text_substrate_contract(
    *,
    acquisition_root: Path,
    manifest: AcquisitionRunManifest,
) -> Path:
    """Require the acquisition manifest to point at a persisted canonical text substrate."""

    substrate_path = manifest.canonical_text_substrate_path
    if substrate_path is None:
        msg = "acquisition manifest is missing canonical_text_substrate_path"
        raise ValueError(msg)
    candidate = Path(substrate_path)
    resolved = candidate if candidate.is_absolute() else acquisition_root / candidate
    if not resolved.exists():
        msg = f"canonical text substrate does not exist: {resolved}"
        raise ValueError(msg)
    return resolved
