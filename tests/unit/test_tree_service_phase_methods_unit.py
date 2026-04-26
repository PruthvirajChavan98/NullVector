"""Unit tests for tree service orchestration: reserve/reuse idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest

from nullvector.domain import TreeBuildRequest, TreeSettings
from nullvector.tree import TreeConflictError, build_tree

from ..support.acquisition_fixtures import convert_legacy_parse_fixture_to_acquisition

FIXTURE_ROOT = Path("fixtures/phase02/inputs")


def _copy_fixture(case_name: str, tmp_path: Path) -> Path:
    import shutil

    destination = tmp_path / case_name
    shutil.copytree(FIXTURE_ROOT / case_name, destination)
    return convert_legacy_parse_fixture_to_acquisition(destination)


def test_reserve_or_reuse_returns_existing_manifest_for_matching_filesystem_run(
    tmp_path: Path,
) -> None:
    """A repeated build with identical inputs returns the same manifest without re-running."""

    acquisition_manifest_path = _copy_fixture("clean_outline", tmp_path)
    request = TreeBuildRequest(
        acquisition_manifest_path=str(acquisition_manifest_path),
        tree_run_id="reuse-check",
    )

    first = build_tree(request)
    second = build_tree(request)

    assert first == second
    assert first.tree_run_id == "reuse-check"
    assert first.committed_node_count >= 1


def test_reserve_raises_conflict_when_settings_differ(tmp_path: Path) -> None:
    """A second build with the same run_id but different settings raises TreeConflictError."""

    acquisition_manifest_path = _copy_fixture("clean_outline", tmp_path)

    build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id="conflict-check",
        )
    )

    with pytest.raises(TreeConflictError):
        build_tree(
            TreeBuildRequest(
                acquisition_manifest_path=str(acquisition_manifest_path),
                tree_run_id="conflict-check",
                settings=TreeSettings(max_pages_per_leaf_node=99),
            )
        )
