"""Public storage backend configuration contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field

from nullvector.domain.common import NonEmptyStr, NullVectorModel


class StorageBackend(StrEnum):
    """Supported persistence backends."""

    FILESYSTEM = "filesystem"
    POSTGRES = "postgres"


class FilesystemStorageConfig(NullVectorModel):
    """Filesystem-backed persistence configuration."""

    backend: Literal[StorageBackend.FILESYSTEM] = StorageBackend.FILESYSTEM
    root: NonEmptyStr | None = None


class PostgresStorageConfig(NullVectorModel):
    """PostgreSQL-backed persistence configuration."""

    # populate_by_name=True allows access via both the alias ("schema") and the
    # Python attribute name ("pg_schema"). The alias keeps the public API stable
    # while avoiding the Pydantic v2 warning that arises when a field is named
    # "schema" (it shadows the deprecated BaseModel.schema() classmethod).
    model_config = ConfigDict(populate_by_name=True)

    backend: Literal[StorageBackend.POSTGRES] = StorageBackend.POSTGRES
    conninfo: NonEmptyStr
    pg_schema: NonEmptyStr = Field(default="public", alias="schema")


StorageConfig = FilesystemStorageConfig | PostgresStorageConfig


__all__ = [
    "FilesystemStorageConfig",
    "PostgresStorageConfig",
    "StorageBackend",
    "StorageConfig",
]
