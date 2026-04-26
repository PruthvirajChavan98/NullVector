"""Shared helpers for client-facing workflows and compatibility wrappers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from nullvector.domain.ledger import SourceDocumentKind
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage._serialization import (
    build_postgres_artifact_ref,
    canonical_json_text,
    is_postgres_ref,
)

_RUN_ID_SAFE = re.compile(r"[^a-z0-9]+")
_MARKDOWN_SUFFIXES = {".md", ".markdown"}
_AUTO_RUN_ID_TOKEN_LENGTH = 12
_ModelT = TypeVar("_ModelT", bound=BaseModel)


def infer_source_kind(
    source_path: str | Path,
    explicit_kind: str | SourceDocumentKind | None,
) -> SourceDocumentKind:
    """Resolve the source kind from an explicit flag or the source-path suffix."""

    if explicit_kind is not None:
        return (
            explicit_kind
            if isinstance(explicit_kind, SourceDocumentKind)
            else SourceDocumentKind(explicit_kind)
        )
    suffix = Path(source_path).suffix.casefold()
    if suffix == ".pdf":
        return SourceDocumentKind.PDF
    if suffix in _MARKDOWN_SUFFIXES:
        return SourceDocumentKind.MARKDOWN
    msg = "--source-kind is required when the source path suffix does not identify a supported kind"
    raise ValueError(msg)


def default_run_id(source_path: str | Path, stage: str) -> str:
    """Generate a readable run identifier from the source stem and stage."""

    return f"{_run_id_prefix(source_path)}-{stage}"


def derived_run_id(existing_run_id: str, *, current_stage: str, target_stage: str) -> str:
    """Derive one related run id from another while preserving readable prefixes."""

    current_suffix = f"-{current_stage}"
    if existing_run_id.endswith(current_suffix):
        return f"{existing_run_id.removesuffix(current_suffix)}-{target_stage}"
    return f"{existing_run_id}-{target_stage}"


def auto_run_id(source_path: str | Path, stage: str, *, token: str | None = None) -> str:
    """Generate a readable unique run identifier while preserving the stage suffix."""

    resolved_token = _resolve_auto_run_token(token)
    return f"{_run_id_prefix(source_path)}-{resolved_token}-{stage}"


def auto_derived_run_id(
    existing_run_id: str,
    *,
    current_stage: str,
    target_stage: str,
    token: str | None = None,
) -> str:
    """Derive one related unique run id from another while preserving the stage suffix."""

    current_suffix = f"-{current_stage}"
    base = (
        existing_run_id.removesuffix(current_suffix)
        if existing_run_id.endswith(current_suffix)
        else existing_run_id
    )
    resolved_token = _resolve_auto_run_token(token)
    if base.endswith(f"-{resolved_token}"):
        return f"{base}-{target_stage}"
    return f"{base}-{resolved_token}-{target_stage}"


def auto_run_id_token(existing_run_id: str, *, stage: str) -> str | None:
    """Return the auto-generated token for one run id when present."""

    suffix = f"-{stage}"
    if not existing_run_id.endswith(suffix):
        return None
    base = existing_run_id.removesuffix(suffix)
    prefix, separator, token = base.rpartition("-")
    if not prefix or not separator:
        return None
    if re.fullmatch(rf"[0-9a-f]{{{_AUTO_RUN_ID_TOKEN_LENGTH}}}", token) is None:
        return None
    return token


def _run_id_prefix(source_path: str | Path) -> str:
    stem = Path(source_path).stem.casefold()
    normalized = _RUN_ID_SAFE.sub("-", stem).strip("-")
    return normalized or "source"


def _resolve_auto_run_token(token: str | None) -> str:
    if token is not None:
        if re.fullmatch(rf"[0-9a-f]{{{_AUTO_RUN_ID_TOKEN_LENGTH}}}", token) is None:
            msg = (
                "auto run-id token must be a "
                f"{_AUTO_RUN_ID_TOKEN_LENGTH}-character lowercase hexadecimal string"
            )
            raise ValueError(msg)
        return token
    return uuid4().hex[:_AUTO_RUN_ID_TOKEN_LENGTH]


def provider_identity_for(source_kind: SourceDocumentKind) -> str:
    """Map source kinds to the framework-owned provider identities."""

    if source_kind is SourceDocumentKind.MARKDOWN:
        return "markdown_native"
    return "native_pymupdf"


def manifest_ref(
    *,
    run_type: str,
    run_id: str,
    document_id: str,
    artifact_root: str | None,
) -> str:
    """Build the persisted manifest ref for either backend."""

    if artifact_root is None:
        return build_postgres_artifact_ref(
            run_type=run_type,
            run_id=run_id,
            document_id=document_id,
            artifact_path="manifest.json",
        )
    return str(Path(artifact_root) / "manifest.json")


def load_model_artifact(
    model_type: type[_ModelT],
    path: str | Path,
    *,
    storage: StorageConfig | None = None,
) -> _ModelT:
    """Load one model artifact from either filesystem or PostgreSQL storage."""

    ref = str(path)
    if not is_postgres_ref(ref):
        return model_type.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if storage is None:
        msg = f"artifact ref {ref!r} requires storage=<PostgresStorageConfig> to be loaded"
        raise ValueError(msg)
    store = build_document_store(storage)
    return model_type.model_validate_json(canonical_json_text(store.read_json_artifact(ref)))


__all__ = [
    "auto_derived_run_id",
    "auto_run_id",
    "auto_run_id_token",
    "default_run_id",
    "derived_run_id",
    "infer_source_kind",
    "load_model_artifact",
    "manifest_ref",
    "provider_identity_for",
]
