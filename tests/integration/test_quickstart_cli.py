"""Integration coverage for the offline quickstart CLI wrapper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

FIXTURE_ROOT = Path("fixtures/pdfs/phase01")


def _write_markdown_fixture(path: Path) -> Path:
    path.write_text(
        "\n".join(
            (
                "# Overview",
                "NullVector quickstart wraps the offline flow.",
                "",
                "## Details",
                "This section becomes the tree body.",
                "",
                "### Appendix",
                "Final stable notes.",
            )
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.integration
def test_quickstart_cli_runs_markdown_acquire_tree_and_retrieval(tmp_path: Path) -> None:
    markdown_path = _write_markdown_fixture(tmp_path / "quickstart.md")
    artifact_root = tmp_path / "quickstart-artifacts"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/nullvector_quickstart.py",
            "--source-path",
            str(markdown_path),
            "--source-kind",
            "markdown",
            "--build-retrieval",
            "--print-tree-summary",
            "--artifact-root",
            str(artifact_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = cast(dict[str, Any], json.loads(completed.stdout))

    assert payload["source_kind"] == "markdown"
    assert payload["acquisition"]["page_count"] >= 1
    assert payload["tree"]["committed_node_count"] >= 1
    assert payload["retrieval"]["unit_count"] >= 1
    assert len(payload["tree_summary"]["titles"]) >= 1
    assert Path(payload["acquisition"]["manifest_path"]).exists()
    assert Path(payload["tree"]["manifest_path"]).exists()
    assert Path(payload["retrieval"]["manifest_path"]).exists()


@pytest.mark.integration
def test_quickstart_cli_infers_pdf_source_kind(tmp_path: Path) -> None:
    artifact_root = tmp_path / "quickstart-artifacts"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/nullvector_quickstart.py",
            "--source-path",
            str(FIXTURE_ROOT / "born_digital_with_outline.pdf"),
            "--artifact-root",
            str(artifact_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = cast(dict[str, Any], json.loads(completed.stdout))

    assert payload["source_kind"] == "pdf"
    assert payload["retrieval"] is None
    assert payload["tree"]["committed_node_count"] >= 1


@pytest.mark.integration
def test_quickstart_cli_reports_invalid_argument_combinations(tmp_path: Path) -> None:
    markdown_path = _write_markdown_fixture(tmp_path / "invalid.md")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/nullvector_quickstart.py",
            "--source-path",
            str(markdown_path),
            "--source-kind",
            "markdown",
            "--retrieval-run-id",
            "custom-retrieval",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "ValueError: --retrieval-run-id requires --build-retrieval" in completed.stderr
