"""Unit coverage for shared storage serialization helpers."""

from __future__ import annotations

from nullvector.domain.common import BoundingBox
from nullvector.storage._serialization import (
    build_postgres_artifact_ref,
    build_postgres_binary_ref,
    canonical_json_bytes,
    is_postgres_ref,
    json_safe,
    parse_postgres_ref,
    run_identity_matches,
    settings_digest,
)


def test_json_safe_handles_models_sequences_and_plain_values() -> None:
    payload = {
        "bbox": BoundingBox(x0=1.0, y0=2.0, x1=3.0, y1=4.0),
        "values": [1, "two", None],
    }

    assert json_safe(payload) == {
        "bbox": {"x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0},
        "values": [1, "two", None],
    }


def test_canonical_json_and_settings_digest_are_stable() -> None:
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert settings_digest(left) == settings_digest(right)


def test_postgres_artifact_refs_round_trip() -> None:
    artifact_ref = build_postgres_artifact_ref(
        run_type="tree",
        run_id="tree-run-001",
        document_id="doc-123",
        artifact_path="hierarchy/node-cards.json",
    )
    binary_ref = build_postgres_binary_ref(
        run_id="run-001",
        document_id="doc-123",
        asset_path="assets/pages/000001/render-144dpi.png",
    )

    assert is_postgres_ref(artifact_ref) is True
    assert parse_postgres_ref(artifact_ref) == (
        "tree",
        "tree-run-001",
        "doc-123",
        "hierarchy/node-cards.json",
    )
    assert parse_postgres_ref(binary_ref) == (
        "__binary__",
        "run-001",
        "doc-123",
        "assets/pages/000001/render-144dpi.png",
    )


def test_run_identity_matches_uses_canonical_and_legacy_alias_fields() -> None:
    expected_identity = {
        "document_id": "doc-123",
        "fingerprint_sha256": "a" * 64,
        "settings_digest": "b" * 64,
    }

    assert run_identity_matches(
        {
            "document_id": "doc-123",
            "source_fingerprint_sha256": "a" * 64,
            "settings_digest": "b" * 64,
        },
        expected_identity,
    )
    assert run_identity_matches(
        {
            "identity": {
                "document_id": "doc-123",
                "fingerprint_sha256": "a" * 64,
                "settings_digest": "b" * 64,
            }
        },
        expected_identity,
    )
    assert not run_identity_matches(
        {
            "identity": {
                "document_id": "doc-123",
                "fingerprint_sha256": "c" * 64,
                "settings_digest": "b" * 64,
            }
        },
        expected_identity,
    )
