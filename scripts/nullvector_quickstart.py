#!/usr/bin/env python3
"""Offline quickstart CLI for acquisition, tree build, and optional retrieval build."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from nullvector.domain import AcquisitionRequest, NodeCard, SourceDocumentKind, TreeBuildRequest
from nullvector.ingest.acquisition_service import AcquisitionService
from nullvector.retrieval import RetrievalCorpusBuilder
from nullvector.storage import PostgresStorageConfig, StorageConfig, build_document_store
from nullvector.storage._serialization import (
    build_postgres_artifact_ref,
    canonical_json_text,
    is_postgres_ref,
)
from nullvector.tree import build_tree

_RUN_ID_SAFE = re.compile(r"[^a-z0-9]+")
_MARKDOWN_SUFFIXES = {".md", ".markdown"}


def infer_source_kind(
    source_path: str | Path,
    explicit_kind: str | None,
) -> SourceDocumentKind:
    """Resolve the source kind from an explicit flag or the source-path suffix."""

    if explicit_kind is not None:
        return SourceDocumentKind(explicit_kind)
    suffix = Path(source_path).suffix.casefold()
    if suffix == ".pdf":
        return SourceDocumentKind.PDF
    if suffix in _MARKDOWN_SUFFIXES:
        return SourceDocumentKind.MARKDOWN
    msg = (
        "--source-kind is required when the source path suffix does not identify "
        "a supported kind"
    )
    raise ValueError(msg)


def default_run_id(source_path: str | Path, stage: str) -> str:
    """Generate a readable run identifier from the source stem and stage."""

    stem = Path(source_path).stem.casefold()
    normalized = _RUN_ID_SAFE.sub("-", stem).strip("-")
    prefix = normalized or "source"
    return f"{prefix}-{stage}"


def validate_args(args: argparse.Namespace) -> None:
    """Validate cross-flag combinations after argparse parsing."""

    if args.retrieval_run_id and not args.build_retrieval:
        msg = "--retrieval-run-id requires --build-retrieval"
        raise ValueError(msg)
    if args.storage_backend == "postgres":
        if not args.pg_conninfo:
            msg = "--pg-conninfo is required when --storage-backend=postgres"
            raise ValueError(msg)
        if args.artifact_root:
            msg = "--artifact-root is only supported with --storage-backend=filesystem"
            raise ValueError(msg)
        return
    if args.pg_conninfo:
        msg = "--pg-conninfo requires --storage-backend=postgres"
        raise ValueError(msg)
    if args.pg_schema:
        msg = "--pg-schema requires --storage-backend=postgres"
        raise ValueError(msg)


def build_storage_config(args: argparse.Namespace) -> StorageConfig | None:
    """Return the active storage config for the requested backend."""

    if args.storage_backend != "postgres":
        return None
    if args.pg_conninfo is None:
        msg = "--pg-conninfo is required when --storage-backend=postgres"
        raise ValueError(msg)
    return PostgresStorageConfig(
        conninfo=args.pg_conninfo,
        schema=args.pg_schema or "public",
    )


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


def load_node_cards(
    path: str,
    *,
    storage: StorageConfig | None,
) -> tuple[NodeCard, ...]:
    """Load node-card artifacts from either filesystem or PostgreSQL storage."""

    if not is_postgres_ref(path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        if storage is None:
            msg = (
                f"node-card ref {path!r} requires storage=<PostgresStorageConfig> "
                "to be loaded"
            )
            raise ValueError(msg)
        store = build_document_store(storage)
        payload = cast(list[dict[str, Any]], store.read_json_artifact(path))
    return tuple(NodeCard.model_validate(item) for item in payload)


def short_tree_summary(
    node_cards_path: str | None,
    *,
    storage: StorageConfig | None,
) -> dict[str, Any] | None:
    """Return a compact tree summary for human inspection."""

    if node_cards_path is None:
        return None
    node_cards = load_node_cards(node_cards_path, storage=storage)
    return {
        "node_card_count": len(node_cards),
        "titles": [card.title for card in node_cards[:5]],
    }


def format_summary(summary: dict[str, Any]) -> str:
    """Render the stable quickstart summary payload."""

    return canonical_json_text(summary, pretty=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse quickstart CLI arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-path", required=True, help="Path to the source PDF or Markdown.")
    parser.add_argument(
        "--source-kind",
        choices=tuple(kind.value for kind in SourceDocumentKind),
        help="Optional explicit source kind; inferred from the file suffix when omitted.",
    )
    parser.add_argument(
        "--acquisition-run-id",
        help="Optional acquisition run id. Defaults to <source-stem>-acquisition.",
    )
    parser.add_argument(
        "--tree-run-id",
        help="Optional tree run id. Defaults to <source-stem>-tree.",
    )
    parser.add_argument(
        "--build-retrieval",
        action="store_true",
        help="Build a retrieval corpus after tree synthesis.",
    )
    parser.add_argument(
        "--retrieval-run-id",
        help="Optional retrieval run id. Defaults to <source-stem>-retrieval.",
    )
    parser.add_argument(
        "--storage-backend",
        choices=("filesystem", "postgres"),
        default="filesystem",
        help="Persistence backend for all invoked services.",
    )
    parser.add_argument(
        "--artifact-root",
        help="Filesystem artifact root passed into acquisition.",
    )
    parser.add_argument(
        "--pg-conninfo",
        help="PostgreSQL conninfo string used when --storage-backend=postgres.",
    )
    parser.add_argument(
        "--pg-schema",
        help="Optional PostgreSQL schema name when --storage-backend=postgres.",
    )
    parser.add_argument(
        "--print-tree-summary",
        action="store_true",
        help="Include a short tree summary in the final output.",
    )
    args = parser.parse_args(argv)
    validate_args(args)
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline quickstart flow and print a stable summary payload."""

    try:
        args = parse_args(argv)
        source_path = Path(args.source_path)
        source_kind = infer_source_kind(source_path, args.source_kind)
        storage = build_storage_config(args)

        acquisition_run_id = args.acquisition_run_id or default_run_id(source_path, "acquisition")
        tree_run_id = args.tree_run_id or default_run_id(source_path, "tree")
        retrieval_run_id = args.retrieval_run_id or default_run_id(source_path, "retrieval")

        acquisition_manifest = AcquisitionService(storage=storage).acquire(
            AcquisitionRequest(
                source_path=str(source_path),
                acquisition_run_id=acquisition_run_id,
                artifact_root=args.artifact_root,
                source_kind=source_kind,
                provider_identity=provider_identity_for(source_kind),
            )
        )
        acquisition_manifest_path = manifest_ref(
            run_type="acquisition",
            run_id=acquisition_run_id,
            document_id=acquisition_manifest.document_id,
            artifact_root=acquisition_manifest.artifact_root,
        )

        tree_manifest = build_tree(
            TreeBuildRequest(
                acquisition_manifest_path=acquisition_manifest_path,
                tree_run_id=tree_run_id,
                summarize=False,
            ),
            storage=storage,
        )
        tree_manifest_path = manifest_ref(
            run_type="tree",
            run_id=tree_run_id,
            document_id=tree_manifest.document_id,
            artifact_root=tree_manifest.artifact_root,
        )

        retrieval_summary: dict[str, Any] | None = None
        if args.build_retrieval:
            retrieval_manifest = RetrievalCorpusBuilder(storage=storage).build(
                acquisition_manifest_path=acquisition_manifest_path,
                tree_manifest_path=tree_manifest_path,
                retrieval_run_id=retrieval_run_id,
            )
            retrieval_summary = {
                "run_id": retrieval_run_id,
                "manifest_path": manifest_ref(
                    run_type="retrieval",
                    run_id=retrieval_run_id,
                    document_id=retrieval_manifest.document_id,
                    artifact_root=retrieval_manifest.artifact_root,
                ),
                "unit_count": retrieval_manifest.unit_count,
            }

        summary: dict[str, Any] = {
            "storage_backend": args.storage_backend,
            "source_kind": source_kind.value,
            "source_path": str(source_path),
            "document_id": acquisition_manifest.document_id,
            "acquisition": {
                "run_id": acquisition_run_id,
                "manifest_path": acquisition_manifest_path,
                "page_count": acquisition_manifest.page_count,
                "selected_outline_source": acquisition_manifest.selected_outline_source.value,
            },
            "tree": {
                "run_id": tree_run_id,
                "manifest_path": tree_manifest_path,
                "committed_node_count": tree_manifest.committed_node_count,
                "unassigned_span_count": tree_manifest.unassigned_span_count,
            },
            "retrieval": retrieval_summary,
        }
        if args.print_tree_summary:
            summary["tree_summary"] = short_tree_summary(
                tree_manifest.node_cards_path,
                storage=storage,
            )

        print(format_summary(summary))
        return 0
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - exercised via subprocess tests
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
