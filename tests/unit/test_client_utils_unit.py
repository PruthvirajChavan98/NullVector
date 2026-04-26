"""Unit coverage for client-facing run-id helpers."""

from __future__ import annotations

import re

import pytest

from nullvector._client_utils import (
    auto_derived_run_id,
    auto_run_id,
    auto_run_id_token,
)


def test_auto_run_id_uses_normalized_prefix_and_token() -> None:
    run_id = auto_run_id(
        "Q1 Revenue Deck!!.pdf",
        "tree",
        token="abcdef123456",
    )

    assert run_id == "q1-revenue-deck-abcdef123456-tree"


def test_auto_derived_run_id_appends_token_for_deterministic_upstream() -> None:
    run_id = auto_derived_run_id(
        "report-acquisition",
        current_stage="acquisition",
        target_stage="tree",
        token="abcdef123456",
    )

    assert run_id == "report-abcdef123456-tree"


def test_auto_derived_run_id_swaps_stage_when_reusing_explicit_token() -> None:
    run_id = auto_derived_run_id(
        "report-abcdef123456-acquisition",
        current_stage="acquisition",
        target_stage="tree",
        token="abcdef123456",
    )

    assert run_id == "report-abcdef123456-tree"


def test_auto_run_id_token_extracts_token_from_auto_generated_run_id() -> None:
    assert auto_run_id_token("report-abcdef123456-tree", stage="tree") == "abcdef123456"
    assert auto_run_id_token("report-tree", stage="tree") is None
    assert auto_run_id_token("report-abcdef123456-tree", stage="retrieval") is None


def test_auto_derived_run_id_generates_unique_token_when_omitted() -> None:
    run_id = auto_derived_run_id(
        "report-acquisition",
        current_stage="acquisition",
        target_stage="tree",
    )

    assert re.fullmatch(r"report-[0-9a-f]{12}-tree", run_id) is not None


def test_auto_run_id_rejects_invalid_manual_token() -> None:
    with pytest.raises(ValueError, match="12-character lowercase hexadecimal string"):
        auto_run_id("report.pdf", "tree", token="INVALID")
