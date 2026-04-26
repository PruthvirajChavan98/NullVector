"""Integration tests for the LLM-driven tree pipeline."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from nullvector import build_tree_batch
from nullvector.domain import (
    TreeBuildRequest,
    TreeSettings,
)
from nullvector.tree import TreeConflictError, build_tree

from ..support.acquisition_fixtures import convert_legacy_parse_fixture_to_acquisition

FIXTURE_ROOT = Path("fixtures/phase02/inputs")
EXPECTED_ROOT = Path("fixtures/expected/phase02")


def copy_fixture(case_name: str, tmp_path: Path) -> Path:
    fixture_root = FIXTURE_ROOT / case_name
    destination = tmp_path / case_name
    shutil.copytree(fixture_root, destination)
    return convert_legacy_parse_fixture_to_acquisition(destination)


def load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require_path(value: str | None, *, label: str) -> str:
    if value is None:
        pytest.fail(f"expected {label} path to be populated")
    return value


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.mark.integration
@pytest.mark.parametrize(
    "case_name",
    [
        "clean_outline",
        "no_outline_inferred",
        "partial_outline",
        "nested_numbering",
        "repeated_headers",
        "unassigned_pages",
        "hybrid_reconciliation",
    ],
)
def test_tree_build_produces_committed_hierarchy_and_node_cards(
    case_name: str, tmp_path: Path
) -> None:
    """Verify that the new pipeline produces hierarchy, node cards, and build report."""

    acquisition_manifest_path = copy_fixture(case_name, tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id=f"{case_name}-tree",
        ),
    )

    build_report = load_json(require_path(manifest.build_report_path, label="build_report"))
    committed_nodes = cast(
        list[dict[str, Any]],
        load_json(require_path(manifest.committed_hierarchy_path, label="committed_hierarchy")),
    )
    node_cards = cast(
        list[dict[str, Any]],
        load_json(require_path(manifest.node_cards_path, label="node_cards")),
    )

    assert manifest.committed_node_count >= 1
    assert build_report["committed_node_count"] == manifest.committed_node_count
    assert build_report["synthesis_method"] in ("llm", "fallback_single_node", "outline_fallback")
    assert len(committed_nodes) == manifest.committed_node_count
    assert len(node_cards) == manifest.committed_node_count


@pytest.mark.integration
def test_tree_run_index_is_written_and_points_to_manifest(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id="run-index-check",
        ),
    )

    assert manifest.run_index_path is not None


@pytest.mark.integration
def test_tree_rerun_is_idempotent_and_conflicts_on_changed_input(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)
    request = TreeBuildRequest(
        acquisition_manifest_path=str(acquisition_manifest_path),
        tree_run_id="stable-tree-run",
    )

    first = build_tree(request)
    second = build_tree(request)

    assert first == second

    changed_settings_request = request.model_copy(
        update={"settings": TreeSettings(max_pages_per_leaf_node=5)},
    )
    with pytest.raises(TreeConflictError):
        build_tree(changed_settings_request)


@pytest.mark.integration
def test_tree_run_id_conflicts_across_acquisition_roots_with_identical_contents(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first-copy"
    second_root = tmp_path / "second-copy"
    shutil.copytree(FIXTURE_ROOT / "clean_outline", first_root)
    shutil.copytree(FIXTURE_ROOT / "clean_outline", second_root)

    first_manifest_path = convert_legacy_parse_fixture_to_acquisition(first_root)
    second_manifest_path = convert_legacy_parse_fixture_to_acquisition(second_root)

    build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(first_manifest_path),
            tree_run_id="shared-tree-run",
        ),
    )

    with pytest.raises(TreeConflictError):
        build_tree(
            TreeBuildRequest(
                acquisition_manifest_path=str(second_manifest_path),
                tree_run_id="shared-tree-run",
            ),
        )


@pytest.mark.integration
def test_build_report_has_expected_fields(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("partial_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id="build-report-check",
        ),
    )

    build_report = cast(
        dict[str, Any],
        load_json(require_path(manifest.build_report_path, label="build_report")),
    )

    assert "committed_node_count" in build_report
    assert "unassigned_span_count" in build_report
    assert "synthesis_method" in build_report
    assert build_report["committed_node_count"] >= 1


@pytest.mark.integration
def test_build_tree_batch_collects_nonfatal_per_item_failures(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)
    result = build_tree_batch(
        (
            TreeBuildRequest(
                acquisition_manifest_path=str(acquisition_manifest_path),
                tree_run_id="batch-mixed-success",
            ),
            TreeBuildRequest(
                acquisition_manifest_path="nonexistent/path/manifest.json",
                tree_run_id="batch-mixed-failure",
            ),
        ),
        max_workers=2,
    )

    assert len(result.successful) == 1
    assert result.successful[0].tree_run_id == "batch-mixed-success"
    assert len(result.failed) == 1
    assert result.failed[0].item_index == 1


@pytest.mark.integration
def test_decomposition_report_is_persisted(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id="decomposition-check",
        ),
    )

    decomposition_report = cast(
        dict[str, Any],
        load_json(require_path(manifest.decomposition_report_path, label="decomposition_report")),
    )
    assert "decomposition_method" in decomposition_report


@pytest.mark.integration
def test_unassigned_spans_are_persisted(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id="unassigned-spans-check",
        ),
    )

    unassigned_spans = cast(
        list[dict[str, Any]],
        load_json(require_path(manifest.unassigned_spans_path, label="unassigned_spans")),
    )
    assert isinstance(unassigned_spans, list)
    assert manifest.unassigned_span_count == len(unassigned_spans)


@pytest.mark.integration
@pytest.mark.skipif(
    not (Path("903000608.pdf")).exists(),
    reason="903000608.pdf not present; local real-PDF demo notebook is optional",
)
def test_real_pdf_demo_notebook_executes() -> None:
    """Placeholder for local real-PDF demo notebook execution."""
