#!/usr/bin/env python3
"""Offline quickstart CLI for acquisition, tree build, and optional retrieval build."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from nullvector._client_utils import (
    default_run_id as _default_run_id,
)
from nullvector._client_utils import (
    infer_source_kind as _infer_source_kind,
)
from nullvector._client_utils import (
    load_model_artifact,
)
from nullvector._client_utils import (
    manifest_ref as _manifest_ref,
)
from nullvector._client_utils import (
    provider_identity_for as _provider_identity_for,
)
from nullvector.client import NullVectorClient
from nullvector.constants import DEFAULT_ACQUISITION_ARTIFACT_ROOT
from nullvector.domain import (
    AcquisitionRunManifest,
    NodeCard,
    SourceDocumentKind,
    TreeBuildManifest,
)
from nullvector.retrieval import load_retrieval_manifest
from nullvector.storage import PostgresStorageConfig, StorageConfig, build_document_store
from nullvector.storage._serialization import (
    canonical_json_text,
    is_postgres_ref,
    parse_postgres_ref,
)


def infer_source_kind(
    source_path: str | Path,
    explicit_kind: str | SourceDocumentKind | None,
) -> SourceDocumentKind:
    """Resolve the source kind from an explicit flag or the source-path suffix."""

    return _infer_source_kind(source_path, explicit_kind)


def default_run_id(source_path: str | Path, stage: str) -> str:
    """Generate a readable run identifier from the source stem and stage."""

    return _default_run_id(source_path, stage)


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

    return _provider_identity_for(source_kind)


def manifest_ref(
    *,
    run_type: str,
    run_id: str,
    document_id: str,
    artifact_root: str | None,
) -> str:
    """Build the persisted manifest ref for either backend."""

    return _manifest_ref(
        run_type=run_type,
        run_id=run_id,
        document_id=document_id,
        artifact_root=artifact_root,
    )


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
            msg = f"node-card ref {path!r} requires storage=<PostgresStorageConfig> to be loaded"
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


def run_id_from_manifest_ref(manifest_path: str, *, run_type: str) -> str:
    """Extract one persisted run id from a manifest ref on either backend."""

    if is_postgres_ref(manifest_path):
        actual_run_type, run_id, _, artifact_path = parse_postgres_ref(manifest_path)
        if actual_run_type != run_type or artifact_path != "manifest.json":
            msg = f"manifest ref {manifest_path!r} does not target {run_type}/manifest.json"
            raise ValueError(msg)
        return run_id
    path = Path(manifest_path)
    if path.name != "manifest.json":
        msg = f"manifest path {manifest_path!r} does not end with manifest.json"
        raise ValueError(msg)
    return path.parent.name


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
        help="Optional acquisition run id. Defaults to an auto-generated unique run id.",
    )
    parser.add_argument(
        "--tree-run-id",
        help="Optional tree run id. Defaults to an auto-generated unique run id.",
    )
    parser.add_argument(
        "--build-retrieval",
        action="store_true",
        help="Build a retrieval corpus after tree synthesis.",
    )
    parser.add_argument(
        "--retrieval-run-id",
        help="Optional retrieval run id. Defaults to an auto-generated unique run id.",
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
        workspace_root = Path(args.artifact_root or DEFAULT_ACQUISITION_ARTIFACT_ROOT)
        client = NullVectorClient(storage_path=workspace_root, storage=storage)

        if args.build_retrieval:
            result = client.ingest(
                source_path,
                source_kind=source_kind,
                preset="general_document",
                acquisition_run_id=args.acquisition_run_id,
                tree_run_id=args.tree_run_id,
                retrieval_run_id=args.retrieval_run_id,
            )
            acquisition_manifest_path = result.acquisition_manifest_path
            tree_manifest_path = result.tree_manifest_path
            retrieval_manifest_path = result.retrieval_manifest_path
            acquisition_manifest = load_model_artifact(
                AcquisitionRunManifest,
                acquisition_manifest_path,
                storage=storage,
            )
            tree_manifest = load_model_artifact(
                TreeBuildManifest,
                tree_manifest_path,
                storage=storage,
            )
            retrieval_manifest = load_retrieval_manifest(
                retrieval_manifest_path,
                storage=storage,
            )
            retrieval_summary: dict[str, Any] | None = {
                "run_id": (
                    args.retrieval_run_id
                    or run_id_from_manifest_ref(retrieval_manifest_path, run_type="retrieval")
                ),
                "manifest_path": retrieval_manifest_path,
                "unit_count": retrieval_manifest.unit_count,
            }
        else:
            acquisition_manifest, acquisition_manifest_path = client.acquire(
                source_path,
                source_kind=source_kind,
                preset="general_document",
                acquisition_run_id=args.acquisition_run_id,
            )
            tree_manifest = client.build_tree(
                acquisition_manifest_path,
                tree_run_id=args.tree_run_id,
                preset="general_document",
                summarize=False,
            )
            tree_manifest_path = manifest_ref(
                run_type="tree",
                run_id=tree_manifest.tree_run_id,
                document_id=tree_manifest.document_id,
                artifact_root=tree_manifest.artifact_root,
            )
            retrieval_summary = None

        summary: dict[str, Any] = {
            "storage_backend": args.storage_backend,
            "source_kind": source_kind.value,
            "source_path": str(source_path),
            "document_id": acquisition_manifest.document_id,
            "acquisition": {
                "run_id": acquisition_manifest.acquisition_run_id,
                "manifest_path": acquisition_manifest_path,
                "page_count": acquisition_manifest.page_count,
                "selected_outline_source": acquisition_manifest.selected_outline_source.value,
            },
            "tree": {
                "run_id": tree_manifest.tree_run_id,
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
