"""Unit tests for Phase 02 tree pipeline helpers that survived the VLM pivot."""

from __future__ import annotations

from nullvector.tree.hierarchy import generate_node_id


def test_generate_node_id_is_stable() -> None:
    first = generate_node_id(
        document_id="d" * 64,
        path=("Root", "Child"),
        level=2,
        page=3,
        start_offset=10,
        end_offset=20,
        span_start_page=3,
    )
    second = generate_node_id(
        document_id="d" * 64,
        path=("Root", "Child"),
        level=2,
        page=3,
        start_offset=10,
        end_offset=20,
        span_start_page=3,
    )

    assert first == second
