"""Integration tests for the deterministic Phase 02 tree pipeline."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from nullvector.domain import (
    DocumentFingerprint,
    OcrMode,
    OutlineQualityReport,
    OutlineSource,
    PageLedgerRow,
    ParserSettings,
    ParseRunManifest,
    TreeBuildRequest,
    TreeSettings,
)
from nullvector.domain.models import PageExtractionMethod
from nullvector.ingest.artifacts import settings_digest
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    LiteLLMProviderConfig,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.tree import TreeConflictError, TreePipelineError, build_tree

from ..support.acquisition_fixtures import convert_legacy_parse_fixture_to_acquisition

FIXTURE_ROOT = Path("fixtures/phase02/inputs")
EXPECTED_ROOT = Path("fixtures/expected/phase02")


def copy_fixture(case_name: str, tmp_path: Path) -> Path:
    fixture_root = FIXTURE_ROOT / case_name
    destination = tmp_path / case_name
    shutil.copytree(fixture_root, destination)
    return convert_legacy_parse_fixture_to_acquisition(destination)


def load_expected(case_name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((EXPECTED_ROOT / f"{case_name}.json").read_text(encoding="utf-8")),
    )


def load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_decomposition_acquisition_fixture(tmp_path: Path) -> Path:
    document_id = "9" * 64
    parse_run_id = "large-leaf-decomposition"
    root = tmp_path / "large_leaf_decomposition"
    (root / "source").mkdir(parents=True)
    (root / "outline").mkdir(parents=True)
    (root / "ledger").mkdir(parents=True)
    (root / "pages").mkdir(parents=True)

    page_texts = (
        "Root\nintro line\nbody line one\nbody line two\nbody line three",
        "SECTION alpha\nalpha body one.\nalpha body two.\nalpha body three.\nalpha body four.",
        "SECTION beta\nbeta body one.\nbeta body two.\nbeta body three.\nbeta body four.",
        "Appendix\nappendix body one.\nappendix body two.",
    )
    text_offset = 0
    ledger_rows: list[PageLedgerRow] = []
    for page_index, text in enumerate(page_texts):
        page_dir = root / "pages" / f"{page_index:06d}"
        page_dir.mkdir(parents=True, exist_ok=True)
        text_path = page_dir / "native.txt"
        text_path.write_text(text, encoding="utf-8")
        text_length = len(text)
        ledger_rows.append(
            PageLedgerRow(
                document_id=document_id,
                parse_run_id=parse_run_id,
                source_path="source/original.pdf",
                page_index=page_index,
                extraction_method=PageExtractionMethod.NATIVE_TEXT,
                needs_ocr=False,
                native_text_available=True,
                ocr_mode=OcrMode.NONE,
                text_offset_start=text_offset,
                text_offset_end=text_offset + text_length,
                text_length=text_length,
                text_sha256=_hash_text(text),
                native_text_sha256=_hash_text(text),
                native_word_count=len(text.split()),
                native_char_count=len("".join(text.split())),
                text_artifact_path=str(Path("pages") / f"{page_index:06d}" / "native.txt"),
                native_text_artifact_path=str(Path("pages") / f"{page_index:06d}" / "native.txt"),
            )
        )
        text_offset += text_length

    (root / "ledger" / "page-ledger.jsonl").write_text(
        "\n".join(row.model_dump_json() for row in ledger_rows) + "\n",
        encoding="utf-8",
    )
    outline_entries = [
        {
            "level": 1,
            "title": "Root",
            "page_index": 0,
            "source": "pymupdf",
        },
        {
            "level": 1,
            "title": "Appendix",
            "page_index": 3,
            "source": "pymupdf",
        },
    ]
    (root / "outline" / "selected.json").write_text(
        json.dumps(
            {"selected_source": "pymupdf", "entries": outline_entries},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    for relative in (
        root / "outline" / "pymupdf.normalized.json",
        root / "outline" / "pymupdf.rich.json",
        root / "outline" / "pypdf.normalized.json",
    ):
        relative.write_text("[]", encoding="utf-8")

    fingerprint = DocumentFingerprint(
        document_id=document_id,
        source_path="source/original.pdf",
        sha256=document_id,
        file_size_bytes=128,
        page_count=len(page_texts),
    )
    settings = ParserSettings()
    manifest = ParseRunManifest(
        parse_run_id=parse_run_id,
        document_id=document_id,
        artifact_root=".",
        fingerprint=fingerprint,
        settings=settings,
        settings_digest=settings_digest(settings),
        selected_outline_source=OutlineSource.PYMUPDF,
        outline_quality_reports=(
            OutlineQualityReport(
                source=OutlineSource.PYMUPDF,
                entry_count=2,
                null_destination_count=0,
                empty_title_count=0,
                non_monotonic_count=0,
                invalid_level_count=0,
                max_depth=1,
                score=200,
            ),
        ),
        ledger_path="ledger/page-ledger.jsonl",
        selected_outline_path="outline/selected.json",
        source_copy_path="source/original.pdf",
        pymupdf_outline_path="outline/pymupdf.normalized.json",
        pymupdf_rich_outline_path="outline/pymupdf.rich.json",
        pypdf_outline_path="outline/pypdf.normalized.json",
        page_count=len(page_texts),
    )
    (root / "source" / "original.pdf").write_bytes(b"%PDF-1.4 synthetic fixture")
    (root / "source" / "fingerprint.json").write_text(
        json.dumps(fingerprint.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return convert_legacy_parse_fixture_to_acquisition(root)


def make_summary_gateway(tmp_path: Path) -> GatewayService:
    return GatewayService(
        GatewayConfig(
            provider=LiteLLMProviderConfig(model="test-model"),
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "summarize_leaf_node": NoopScriptedResponse(
                    output_json={"summary": "leaf summary", "keywords": ["leaf"]}
                ),
                "summarize_parent_node": NoopScriptedResponse(
                    output_json={"summary": "parent summary", "keywords": ["parent"]}
                ),
            }
        ),
    )


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
    acquisition_manifest_path = copy_fixture(case_name, tmp_path)
    expected = load_expected(case_name)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
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
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id="run-index-check",
        ),
    )
    run_index = cast(dict[str, Any], load_json(manifest.run_index_path))

    assert Path(manifest.run_index_path).exists()
    assert run_index["registry_root"] == manifest.registry_root
    assert run_index["manifest_path"] == str(Path(manifest.artifact_root) / "manifest.json")
    assert run_index["acquisition_manifest_path"] == str(acquisition_manifest_path.resolve())
    assert run_index["acquisition_artifact_identity"] == str(acquisition_manifest_path.resolve())
    assert run_index["document_id"] == manifest.document_id


def test_strategy_report_is_persisted_for_default_builds(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id="strategy-default-check",
        ),
    )
    report = cast(dict[str, Any], load_json(manifest.strategy_execution_report_path or ""))
    headings = cast(dict[str, Any], load_json(manifest.headings_path))

    assert manifest.strategy_execution_report_path is not None
    assert Path(manifest.strategy_execution_report_path).exists()
    assert report["selected_strategy"] == "outline_only"
    assert report["attempted_strategies"][0] == "outline_only"
    assert headings["strategy"] == "outline_only"
    assert headings["effective_trust_mode"] == "outline_primary"
    assert "/strategy/attempts/" in manifest.headings_path


def test_strategy_attempt_artifacts_are_written(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("no_outline_inferred", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id="strategy-attempt-artifacts",
        ),
    )

    assert Path(manifest.headings_path).exists()
    assert Path(manifest.committed_hierarchy_path).exists()
    assert Path(manifest.verification_report_path).exists()
    headings = cast(dict[str, Any], load_json(manifest.headings_path))
    assert "strategy" in headings
    assert "effective_trust_mode" in headings
    assert "/strategy/attempts/" in manifest.committed_hierarchy_path


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
        update={"settings": TreeSettings(heading_score_keep_threshold=35)},
    )
    with pytest.raises(TreeConflictError):
        build_tree(changed_settings_request)

    other_manifest_path = acquisition_manifest_path.with_name("manifest.alt.json")
    other_manifest_path.write_text(
        acquisition_manifest_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(TreeConflictError):
        build_tree(
            TreeBuildRequest(
                acquisition_manifest_path=str(other_manifest_path),
                tree_run_id="stable-tree-run",
            ),
        )


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


def test_build_report_counts_follow_reconciled_candidate_sequence(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("partial_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
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


def test_tree_build_summarization_is_opt_in(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)

    manifest_without_summaries = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id=f"summary-disabled-{tmp_path.name}",
            summarize=False,
        ),
    )
    cards_without_summaries = cast(
        list[dict[str, Any]],
        load_json(manifest_without_summaries.node_cards_path),
    )
    assert manifest_without_summaries.node_summaries_path is None
    assert all(card.get("summary") is None for card in cards_without_summaries)

    manifest_with_summaries = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id=f"summary-enabled-{tmp_path.name}",
            summarize=True,
        ),
        gateway=make_summary_gateway(tmp_path),
    )
    cards_with_summaries = cast(
        list[dict[str, Any]], load_json(manifest_with_summaries.node_cards_path)
    )

    assert manifest_with_summaries.node_summaries_path is not None
    assert Path(manifest_with_summaries.node_summaries_path).exists()
    assert any(card.get("summary") is not None for card in cards_with_summaries)
    assert any(card.get("summary_method") is not None for card in cards_with_summaries)


def test_tree_build_raises_when_summarize_enabled_without_gateway(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)

    with pytest.raises(TreePipelineError, match="summarize=True requires a configured gateway"):
        build_tree(
            TreeBuildRequest(
                acquisition_manifest_path=str(acquisition_manifest_path),
                tree_run_id="summary-missing-gateway",
                summarize=True,
            ),
        )


def test_build_path_applies_large_leaf_decomposition(tmp_path: Path) -> None:
    acquisition_manifest_path = write_decomposition_acquisition_fixture(tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id="decomposition-build",
            settings=TreeSettings(max_pages_per_leaf_node=2),
        ),
    )
    report = cast(dict[str, Any], load_json(manifest.decomposition_report_path or ""))
    committed_nodes = cast(list[dict[str, Any]], load_json(manifest.committed_hierarchy_path))
    node_cards = cast(list[dict[str, Any]], load_json(manifest.node_cards_path))

    assert manifest.decomposition_report_path is not None
    assert report["decomposition_method"] == "deterministic"
    assert report["new_child_count"] == 2
    assert report["empty_parent_count"] == 0
    assert any(node["title"] == "SECTION alpha" for node in committed_nodes)
    assert any(node["title"] == "SECTION beta" for node in committed_nodes)
    assert any(card["title"] == "SECTION alpha" for card in node_cards)
    assert all("owned_spans" in node for node in committed_nodes)
    assert all("owned_spans" in card for card in node_cards)


def test_verification_report_uses_tree_specific_node_results(tmp_path: Path) -> None:
    acquisition_manifest_path = copy_fixture("clean_outline", tmp_path)

    manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
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
    assert first_source_line(cells[0]).startswith("# NullVector Progress Notebook")
    title_cell = "".join(cells[0].get("source", []))
    assert "major-changes-v2" in title_cell
    assert "Phase F-J" in title_cell

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
        "# NullVector Real PDF Parser + Tree Demo Notebook"
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
    assert summary["pdf"]["acquisition_mode"] in {
        "reused_local_manifest",
        "acquired_fresh",
    }
    assert summary["acquisition"]["page_count"] > 0
    assert summary["tree"]["committed_node_count"] >= 1
    assert summary["representative_pages"]
