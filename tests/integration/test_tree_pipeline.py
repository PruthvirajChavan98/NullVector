"""Integration tests for the deterministic Phase 02 tree pipeline."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from strataforge.domain import TreeBuildRequest, TreeSettings
from strataforge.tree import TreeConflictError, build_tree

FIXTURE_ROOT = Path("fixtures/phase02/inputs")
EXPECTED_ROOT = Path("fixtures/expected/phase02")


def copy_fixture(case_name: str, tmp_path: Path) -> Path:
    fixture_root = FIXTURE_ROOT / case_name
    destination = tmp_path / case_name
    shutil.copytree(fixture_root, destination)
    return destination / "manifest.json"


def load_expected(case_name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((EXPECTED_ROOT / f"{case_name}.json").read_text(encoding="utf-8")),
    )


def load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def first_source_line(cell: dict[str, Any]) -> str:
    for line in cell.get("source", []):
        stripped = str(line).strip()
        if stripped:
            return stripped
    return ""


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
def test_tree_build_matches_expected_fixture_outputs(case_name: str, tmp_path: Path) -> None:
    parse_manifest_path = copy_fixture(case_name, tmp_path)
    expected = load_expected(case_name)

    manifest = build_tree(
        TreeBuildRequest(
            parse_manifest_path=str(parse_manifest_path),
            tree_run_id=f"{case_name}-tree",
        ),
    )

    build_report = load_json(manifest.build_report_path)
    committed_nodes = cast(list[dict[str, Any]], load_json(manifest.committed_hierarchy_path))
    node_cards = cast(list[dict[str, Any]], load_json(manifest.node_cards_path))
    unassigned_spans = cast(list[dict[str, Any]], load_json(manifest.unassigned_spans_path))

    assert build_report["outline_trust_mode"] == expected["outline_trust_mode"]
    assert [card["title"] for card in node_cards] == expected["committed_titles"]
    assert {node["title"]: node["level"] for node in committed_nodes} == expected["node_levels"]
    assert {
        node["title"]: [node["page_span"]["start_page"], node["page_span"]["end_page"]]
        for node in committed_nodes
    } == expected["node_spans"]
    assert [
        {
            "reason": span["reason"],
            "start_page": span["page_span"]["start_page"],
            "end_page": span["page_span"]["end_page"],
        }
        for span in unassigned_spans
    ] == expected["unassigned_spans"]
    if "suppressed_title" in expected:
        assert expected["suppressed_title"] not in [card["title"] for card in node_cards]


def test_tree_run_index_is_written_and_points_to_manifest(tmp_path: Path) -> None:
    parse_manifest_path = copy_fixture("clean_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            parse_manifest_path=str(parse_manifest_path),
            tree_run_id="run-index-check",
        ),
    )
    run_index = cast(dict[str, Any], load_json(manifest.run_index_path))

    assert Path(manifest.run_index_path).exists()
    assert run_index["registry_root"] == manifest.registry_root
    assert run_index["manifest_path"] == str(Path(manifest.artifact_root) / "manifest.json")
    assert run_index["parse_manifest_path"] == str(parse_manifest_path.resolve())
    assert run_index["parse_artifact_identity"] == str(parse_manifest_path.resolve())
    assert run_index["document_id"] == manifest.document_id


def test_tree_rerun_is_idempotent_and_conflicts_on_changed_input(tmp_path: Path) -> None:
    parse_manifest_path = copy_fixture("clean_outline", tmp_path)
    request = TreeBuildRequest(
        parse_manifest_path=str(parse_manifest_path),
        tree_run_id="stable-tree-run",
    )

    first = build_tree(request)
    second = build_tree(request)

    assert first == second

    changed_settings_request = request.model_copy(
        update={"settings": TreeSettings(heading_score_keep_threshold=35)},
    )
    with pytest.raises(TreeConflictError):
        build_tree(changed_settings_request)

    other_manifest_path = parse_manifest_path.with_name("manifest.alt.json")
    other_manifest_path.write_text(
        parse_manifest_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(TreeConflictError):
        build_tree(
            TreeBuildRequest(
                parse_manifest_path=str(other_manifest_path),
                tree_run_id="stable-tree-run",
            ),
        )


def test_tree_run_id_conflicts_across_parse_roots_with_identical_contents(tmp_path: Path) -> None:
    first_root = tmp_path / "first-copy"
    second_root = tmp_path / "second-copy"
    shutil.copytree(FIXTURE_ROOT / "clean_outline", first_root)
    shutil.copytree(FIXTURE_ROOT / "clean_outline", second_root)

    first_manifest_path = first_root / "manifest.json"
    second_manifest_path = second_root / "manifest.json"

    build_tree(
        TreeBuildRequest(
            parse_manifest_path=str(first_manifest_path),
            tree_run_id="shared-tree-run",
        ),
    )

    with pytest.raises(TreeConflictError):
        build_tree(
            TreeBuildRequest(
                parse_manifest_path=str(second_manifest_path),
                tree_run_id="shared-tree-run",
            ),
        )


def test_build_report_counts_follow_reconciled_candidate_sequence(tmp_path: Path) -> None:
    parse_manifest_path = copy_fixture("partial_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            parse_manifest_path=str(parse_manifest_path),
            tree_run_id="build-report-check",
        ),
    )

    headings = cast(dict[str, Any], load_json(manifest.headings_path))
    build_report = cast(dict[str, Any], load_json(manifest.build_report_path))
    selected = cast(list[dict[str, Any]], headings["selected"])

    assert build_report["candidate_count"] == len(selected)
    assert build_report["selected_candidate_count"] == len(selected)
    assert build_report["outline_candidate_count"] == len(headings["outline"])
    assert build_report["inferred_candidate_count"] == len(headings["inferred"])
    assert build_report["kept_candidate_count"] == sum(
        1 for candidate in selected if candidate["keep"]
    )
    assert build_report["high_confidence_candidate_count"] == sum(
        1 for candidate in selected if candidate["high_confidence"]
    )


def test_verification_report_uses_tree_specific_node_results(tmp_path: Path) -> None:
    parse_manifest_path = copy_fixture("clean_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            parse_manifest_path=str(parse_manifest_path),
            tree_run_id="verification-shape-check",
        ),
    )

    report = cast(dict[str, Any], load_json(manifest.verification_report_path))

    assert report["tree_run_id"] == "verification-shape-check"
    assert all("tree_run_id" in result for result in report["node_results"])
    assert all("parse_run_id" not in result for result in report["node_results"])


def test_progress_notebook_executes_top_to_bottom(tmp_path: Path) -> None:
    output_path = tmp_path / "progress.executed.ipynb"
    subprocess.run(
        [
            sys.executable,
            "scripts/run_progress_notebook.py",
            "--output",
            str(output_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
    )

    executed_notebook = cast(dict[str, Any], json.loads(output_path.read_text(encoding="utf-8")))
    code_cells = [cell for cell in executed_notebook["cells"] if cell.get("cell_type") == "code"]

    assert output_path.exists()
    assert any(cell.get("outputs") for cell in code_cells)
    assert not any(
        output.get("output_type") == "error"
        for cell in code_cells
        for output in cell.get("outputs", [])
    )


def test_progress_notebook_source_has_no_saved_error_outputs() -> None:
    notebook = cast(
        dict[str, Any],
        json.loads(Path("notebooks/progress.ipynb").read_text(encoding="utf-8")),
    )
    code_cells = [cell for cell in notebook["cells"] if cell.get("cell_type") == "code"]

    assert code_cells
    assert not any(
        output.get("output_type") == "error"
        for cell in code_cells
        for output in cell.get("outputs", [])
    )


def test_progress_notebook_structure_matches_repo_contract() -> None:
    notebook = cast(
        dict[str, Any],
        json.loads(Path("notebooks/progress.ipynb").read_text(encoding="utf-8")),
    )
    cells = cast(list[dict[str, Any]], notebook["cells"])

    assert cells[0]["cell_type"] == "markdown"
    assert first_source_line(cells[0]).startswith("# StrataForge Progress Notebook")
    assert "Phase 03" in "".join(cells[0].get("source", []))

    assert cells[1]["cell_type"] == "markdown"
    assert "### Environment" in "".join(cells[1].get("source", []))

    assert cells[2]["cell_type"] == "code"
    assert first_source_line(cells[2]) == "# environment setup"

    assert cells[3]["cell_type"] == "code"
    assert first_source_line(cells[3]) == "# imports"

    assert cells[4]["cell_type"] == "code"
    assert first_source_line(cells[4]) == "# configuration"

    execution_cells = [
        cell
        for cell in cells[5:-1]
        if cell.get("cell_type") == "code" and first_source_line(cell) == "# execution"
    ]
    assert execution_cells

    assert cells[-2]["cell_type"] == "code"
    assert first_source_line(cells[-2]) == "# inspect results"

    assert cells[-1]["cell_type"] == "markdown"
    assert "### Known Limitations" in "".join(cells[-1].get("source", []))


def test_spec_v1_demo_notebook_source_has_no_saved_error_outputs() -> None:
    notebook = cast(
        dict[str, Any],
        json.loads(Path("notebooks/spec_v1_parser_tree_demo.ipynb").read_text(encoding="utf-8")),
    )
    code_cells = [cell for cell in notebook["cells"] if cell.get("cell_type") == "code"]

    assert code_cells
    assert not any(
        output.get("output_type") == "error"
        for cell in code_cells
        for output in cell.get("outputs", [])
    )


def test_spec_v1_demo_notebook_structure_matches_contract() -> None:
    notebook = cast(
        dict[str, Any],
        json.loads(Path("notebooks/spec_v1_parser_tree_demo.ipynb").read_text(encoding="utf-8")),
    )
    cells = cast(list[dict[str, Any]], notebook["cells"])

    assert cells[0]["cell_type"] == "markdown"
    assert first_source_line(cells[0]).startswith(
        "# StrataForge Real PDF Parser + Tree Demo Notebook"
    )

    assert cells[1]["cell_type"] == "markdown"
    assert "### Environment" in "".join(cells[1].get("source", []))

    assert cells[2]["cell_type"] == "code"
    assert first_source_line(cells[2]) == "# environment setup"

    assert cells[3]["cell_type"] == "code"
    assert first_source_line(cells[3]) == "# imports"

    assert cells[4]["cell_type"] == "code"
    assert first_source_line(cells[4]) == "# configuration"

    execution_cells = [
        cell
        for cell in cells[5:-1]
        if cell.get("cell_type") == "code" and first_source_line(cell) == "# execution"
    ]
    assert execution_cells

    assert cells[-2]["cell_type"] == "code"
    assert first_source_line(cells[-2]) == "# inspect results"

    assert cells[-1]["cell_type"] == "markdown"
    assert "### Known Limitations" in "".join(cells[-1].get("source", []))


def test_spec_v1_demo_notebook_executes_when_local_pdf_present(tmp_path: Path) -> None:
    if not Path("903000608.pdf").exists():
        pytest.skip("903000608.pdf not present; local real-PDF demo notebook is optional")

    output_path = tmp_path / "spec_v1_parser_tree_demo.executed.ipynb"
    subprocess.run(
        [
            sys.executable,
            "scripts/run_progress_notebook.py",
            "--notebook",
            "notebooks/spec_v1_parser_tree_demo.ipynb",
            "--output",
            str(output_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
    )

    executed_notebook = cast(dict[str, Any], json.loads(output_path.read_text(encoding="utf-8")))
    inspect_cell = next(
        cast(dict[str, Any], cell)
        for cell in executed_notebook["cells"]
        if cell.get("cell_type") == "code"
        and first_source_line(cast(dict[str, Any], cell)) == "# inspect results"
    )
    inspect_output = "".join(
        text
        for output in inspect_cell.get("outputs", [])
        if output.get("output_type") == "stream"
        for text in output.get("text", [])
    )
    summary = cast(dict[str, Any], json.loads(inspect_output))

    assert output_path.exists()
    assert not any(
        output.get("output_type") == "error"
        for cell in executed_notebook["cells"]
        if cell.get("cell_type") == "code"
        for output in cell.get("outputs", [])
    )
    assert summary["pdf"]["path"].endswith("903000608.pdf")
    assert summary["pdf"]["parse_mode"] in {"reused_local_manifest", "parsed_fresh"}
    assert summary["parse"]["page_count"] > 0
    assert summary["tree"]["committed_node_count"] >= 1
    assert summary["representative_pages"]
