"""Shared runtime context for orchestration-heavy services."""

from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from nullvector.storage.protocol import DocumentStore, RunScopedStore


@dataclass(frozen=True)
class RunContext:
    """Common runtime state for multi-phase service orchestration."""

    store: DocumentStore
    run_store: RunScopedStore
    artifact_root: str | None
    logger: Logger
