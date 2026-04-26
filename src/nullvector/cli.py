"""Installed Typer CLI for the public NullVector DX surface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from nullvector.client import NullVectorClient
from nullvector.domain.ledger import SourceDocumentKind
from nullvector.errors import OperationType, translate_error
from nullvector.storage import PostgresStorageConfig, StorageConfig
from nullvector.storage._serialization import canonical_json_text

app = typer.Typer(
    add_completion=False,
    help="NullVector command-line interface.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _build_storage_config(
    *,
    storage_backend: str,
    pg_conninfo: str | None,
    pg_schema: str | None,
) -> StorageConfig | None:
    if storage_backend != "postgres":
        if pg_conninfo is not None:
            msg = "--pg-conninfo requires --storage-backend=postgres"
            raise ValueError(msg)
        if pg_schema is not None:
            msg = "--pg-schema requires --storage-backend=postgres"
            raise ValueError(msg)
        return None
    if pg_conninfo is None:
        msg = "--pg-conninfo is required when --storage-backend=postgres"
        raise ValueError(msg)
    return PostgresStorageConfig(
        conninfo=pg_conninfo,
        schema=pg_schema or "public",
    )


def _client(
    *,
    storage_path: Path,
    storage_backend: str,
    pg_conninfo: str | None,
    pg_schema: str | None,
) -> NullVectorClient:
    logger = logging.getLogger("nullvector.cli")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return NullVectorClient(
        storage_path=storage_path,
        storage=_build_storage_config(
            storage_backend=storage_backend,
            pg_conninfo=pg_conninfo,
            pg_schema=pg_schema,
        ),
        logger=logger,
    )


def _echo_json(payload: object) -> None:
    typer.echo(canonical_json_text(payload, pretty=True))


def _exit_with_error(exc: Exception, *, operation: OperationType) -> None:
    error = translate_error(exc, operation=operation)
    typer.echo(f"{type(error).__name__}: {error}", err=True)
    raise typer.Exit(code=1) from error


@app.command("ingest")
def ingest_command(
    source_path: Annotated[Path, typer.Argument(help="Path to the source PDF or Markdown file.")],
    preset: Annotated[str, typer.Option(help="Named document preset.")] = "general_document",
    source_kind: Annotated[
        SourceDocumentKind | None,
        typer.Option(help="Optional explicit source kind; inferred from the suffix otherwise."),
    ] = None,
    acquisition_run_id: Annotated[
        str | None,
        typer.Option(help="Optional acquisition run id. Defaults to an auto-generated unique id."),
    ] = None,
    tree_run_id: Annotated[
        str | None,
        typer.Option(help="Optional tree run id. Defaults to an auto-generated unique id."),
    ] = None,
    retrieval_run_id: Annotated[
        str | None,
        typer.Option(help="Optional retrieval run id. Defaults to an auto-generated unique id."),
    ] = None,
    storage_path: Annotated[
        Path,
        typer.Option(help="Workspace root used for local DX state and filesystem artifacts."),
    ] = Path("./workspace"),
    storage_backend: Annotated[
        str,
        typer.Option(help="Persistence backend for the client workspace."),
    ] = "filesystem",
    pg_conninfo: Annotated[
        str | None,
        typer.Option(help="PostgreSQL conninfo string when using the postgres backend."),
    ] = None,
    pg_schema: Annotated[
        str | None,
        typer.Option(help="Optional PostgreSQL schema name."),
    ] = None,
) -> None:
    """Acquire, build a tree, and build retrieval artifacts for one document."""

    try:
        result = _client(
            storage_path=storage_path,
            storage_backend=storage_backend,
            pg_conninfo=pg_conninfo,
            pg_schema=pg_schema,
        ).ingest(
            source_path,
            source_kind=source_kind,
            preset=preset,
            acquisition_run_id=acquisition_run_id,
            tree_run_id=tree_run_id,
            retrieval_run_id=retrieval_run_id,
        )
    except Exception as exc:
        _exit_with_error(exc, operation="ingest")
        return  # unreachable — _exit_with_error raises typer.Exit
    _echo_json(result.model_dump(mode="json"))


@app.command("build-tree")
def build_tree_command(
    acquisition_manifest_path: Annotated[
        str,
        typer.Argument(help="Filesystem path or PostgreSQL ref for the acquisition manifest."),
    ],
    preset: Annotated[str, typer.Option(help="Named document preset.")] = "general_document",
    tree_run_id: Annotated[
        str | None,
        typer.Option(help="Optional tree run id. Defaults to an auto-generated unique id."),
    ] = None,
    summarize: Annotated[
        bool | None,
        typer.Option(
            "--summarize/--no-summarize",
            help="Override preset-driven tree summarization.",
        ),
    ] = None,
    storage_path: Annotated[
        Path,
        typer.Option(help="Workspace root used for local DX state and filesystem artifacts."),
    ] = Path("./workspace"),
    storage_backend: Annotated[
        str,
        typer.Option(help="Persistence backend for the client workspace."),
    ] = "filesystem",
    pg_conninfo: Annotated[
        str | None,
        typer.Option(help="PostgreSQL conninfo string when using the postgres backend."),
    ] = None,
    pg_schema: Annotated[
        str | None,
        typer.Option(help="Optional PostgreSQL schema name."),
    ] = None,
) -> None:
    """Build a tree from one existing acquisition manifest."""

    try:
        manifest = _client(
            storage_path=storage_path,
            storage_backend=storage_backend,
            pg_conninfo=pg_conninfo,
            pg_schema=pg_schema,
        ).build_tree(
            acquisition_manifest_path,
            tree_run_id=tree_run_id,
            preset=preset,
            summarize=summarize,
        )
    except Exception as exc:
        _exit_with_error(exc, operation="tree")
        return
    _echo_json(manifest.model_dump(mode="json"))


@app.command("search")
def search_command(
    query: Annotated[str, typer.Argument(help="Grounded search query.")],
    retrieval_manifest_path: Annotated[
        str | None,
        typer.Option(help="Explicit retrieval manifest path or PostgreSQL ref."),
    ] = None,
    document_id: Annotated[
        str | None,
        typer.Option(help="Document id resolved through the local client catalog."),
    ] = None,
    limit: Annotated[
        int, typer.Option(min=1, help="Maximum number of retrieval hits to return.")
    ] = 10,
    storage_path: Annotated[
        Path,
        typer.Option(help="Workspace root used for local DX state and filesystem artifacts."),
    ] = Path("./workspace"),
    storage_backend: Annotated[
        str,
        typer.Option(help="Persistence backend for the client workspace."),
    ] = "filesystem",
    pg_conninfo: Annotated[
        str | None,
        typer.Option(help="PostgreSQL conninfo string when using the postgres backend."),
    ] = None,
    pg_schema: Annotated[
        str | None,
        typer.Option(help="Optional PostgreSQL schema name."),
    ] = None,
) -> None:
    """Search one retrieval corpus."""

    try:
        hits = _client(
            storage_path=storage_path,
            storage_backend=storage_backend,
            pg_conninfo=pg_conninfo,
            pg_schema=pg_schema,
        ).search(
            query,
            retrieval_manifest_path=retrieval_manifest_path,
            document_id=document_id,
            limit=limit,
        )
    except Exception as exc:
        _exit_with_error(exc, operation="query")
        return
    _echo_json([hit.model_dump(mode="json") for hit in hits])


@app.command("ask")
def ask_command(
    query: Annotated[str, typer.Argument(help="Grounded question to answer.")],
    retrieval_manifest_path: Annotated[
        str | None,
        typer.Option(help="Explicit retrieval manifest path or PostgreSQL ref."),
    ] = None,
    document_id: Annotated[
        str | None,
        typer.Option(help="Document id resolved through the local client catalog."),
    ] = None,
    limit: Annotated[
        int, typer.Option(min=1, help="Maximum number of retrieval hits to inspect.")
    ] = 5,
    storage_path: Annotated[
        Path,
        typer.Option(help="Workspace root used for local DX state and filesystem artifacts."),
    ] = Path("./workspace"),
    storage_backend: Annotated[
        str,
        typer.Option(help="Persistence backend for the client workspace."),
    ] = "filesystem",
    pg_conninfo: Annotated[
        str | None,
        typer.Option(help="PostgreSQL conninfo string when using the postgres backend."),
    ] = None,
    pg_schema: Annotated[
        str | None,
        typer.Option(help="Optional PostgreSQL schema name."),
    ] = None,
) -> None:
    """Answer one grounded question over a retrieval corpus."""

    try:
        response = _client(
            storage_path=storage_path,
            storage_backend=storage_backend,
            pg_conninfo=pg_conninfo,
            pg_schema=pg_schema,
        ).ask(
            query,
            retrieval_manifest_path=retrieval_manifest_path,
            document_id=document_id,
            limit=limit,
        )
    except Exception as exc:
        _exit_with_error(exc, operation="query")
        return
    _echo_json(response.model_dump(mode="json"))


def main() -> None:
    """Run the installed NullVector Typer app."""

    app()


__all__ = [
    "app",
    "main",
]
