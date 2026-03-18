"""Shared retrieval artifact loading helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from nullvector.domain.ledger import (
    AcquisitionRunManifest,
    CanonicalDocumentLedger,
    CanonicalTextSubstrate,
)
from nullvector.domain.tree import (
    HierarchyNode,
    NodeCard,
    NodeSummary,
    TreeBuildManifest,
    UnassignedPageSpan,
    VerificationReport,
)
from nullvector.runtime_validation import validate_canonical_text_substrate_contract
from nullvector.storage._serialization import canonical_json_text, is_postgres_ref
from nullvector.storage.protocol import DocumentStore


def normalize_artifact_ref(ref: str | None) -> str | None:
    """Normalize filesystem refs to absolute paths while preserving pg:// refs."""

    if ref is None or is_postgres_ref(ref):
        return ref
    return str(Path(ref).resolve())


def load_acquisition_manifest(
    store: DocumentStore,
    ref: str,
) -> AcquisitionRunManifest:
    """Load one acquisition manifest from the active store."""

    return AcquisitionRunManifest.model_validate_json(
        canonical_json_text(store.read_json_artifact(ref))
    )


def load_tree_manifest(
    store: DocumentStore,
    ref: str | None,
) -> TreeBuildManifest | None:
    """Load one tree manifest from the active store when present."""

    if ref is None:
        return None
    return TreeBuildManifest.model_validate_json(canonical_json_text(store.read_json_artifact(ref)))


def load_ledger(
    store: DocumentStore,
    acquisition_manifest: AcquisitionRunManifest,
) -> CanonicalDocumentLedger:
    """Load the canonical ledger referenced by one acquisition manifest."""

    return CanonicalDocumentLedger.model_validate_json(
        canonical_json_text(store.read_json_artifact(acquisition_manifest.ledger_path))
    )


def load_text_substrate(
    store: DocumentStore,
    acquisition_manifest: AcquisitionRunManifest,
) -> CanonicalTextSubstrate:
    """Load the canonical text substrate referenced by one acquisition manifest."""

    substrate_ref = validate_canonical_text_substrate_contract(manifest=acquisition_manifest)
    return CanonicalTextSubstrate.model_validate_json(
        canonical_json_text(store.read_json_artifact(substrate_ref))
    )


def load_committed_nodes(
    store: DocumentStore,
    tree_manifest: TreeBuildManifest | None,
) -> tuple[HierarchyNode, ...]:
    """Load committed hierarchy nodes when available."""

    if tree_manifest is None or tree_manifest.committed_hierarchy_path is None:
        return ()
    payload = cast(
        list[dict[str, Any]], store.read_json_artifact(tree_manifest.committed_hierarchy_path)
    )
    return tuple(HierarchyNode.model_validate_json(json.dumps(item)) for item in payload)


def load_node_cards(
    store: DocumentStore,
    tree_manifest: TreeBuildManifest | None,
) -> tuple[NodeCard, ...]:
    """Load persisted node cards when available."""

    if tree_manifest is None or tree_manifest.node_cards_path is None:
        return ()
    payload = cast(list[dict[str, Any]], store.read_json_artifact(tree_manifest.node_cards_path))
    return tuple(NodeCard.model_validate_json(json.dumps(item)) for item in payload)


def load_node_summaries(
    store: DocumentStore,
    tree_manifest: TreeBuildManifest | None,
) -> tuple[NodeSummary, ...]:
    """Load persisted node summaries when available."""

    if tree_manifest is None or tree_manifest.node_summaries_path is None:
        return ()
    payload = cast(
        list[dict[str, Any]], store.read_json_artifact(tree_manifest.node_summaries_path)
    )
    return tuple(NodeSummary.model_validate_json(json.dumps(item)) for item in payload)


def load_verification_report(
    store: DocumentStore,
    tree_manifest: TreeBuildManifest | None,
) -> VerificationReport | None:
    """Load the persisted verification report when available."""

    if tree_manifest is None or tree_manifest.verification_report_path is None:
        return None
    return VerificationReport.model_validate_json(
        canonical_json_text(store.read_json_artifact(tree_manifest.verification_report_path))
    )


def load_unassigned_spans(
    store: DocumentStore,
    tree_manifest: TreeBuildManifest | None,
) -> tuple[UnassignedPageSpan, ...]:
    """Load persisted unassigned spans when available."""

    if tree_manifest is None or tree_manifest.unassigned_spans_path is None:
        return ()
    payload = cast(
        list[dict[str, Any]], store.read_json_artifact(tree_manifest.unassigned_spans_path)
    )
    return tuple(UnassignedPageSpan.model_validate_json(json.dumps(item)) for item in payload)


__all__ = [
    "load_acquisition_manifest",
    "load_committed_nodes",
    "load_ledger",
    "load_node_cards",
    "load_node_summaries",
    "load_text_substrate",
    "load_tree_manifest",
    "load_unassigned_spans",
    "load_verification_report",
    "normalize_artifact_ref",
]
