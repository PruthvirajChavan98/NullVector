"""Integration coverage for the installed Typer CLI surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nullvector.cli import app

runner = CliRunner()


def _write_markdown_fixture(path: Path) -> Path:
    path.write_text(
        "\n".join(
            (
                "# Overview",
                "NullVector CLI smoke coverage.",
                "",
                "## Findings",
                "Command-line ingest should build retrieval artifacts by default.",
                "",
                "### Appendix",
                "CLI ask should resolve the document through the local catalog.",
            )
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.integration
def test_cli_help_lists_phase4_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "ingest" in result.stdout
    assert "build-tree" in result.stdout
    assert "search" in result.stdout
    assert "ask" in result.stdout


@pytest.mark.integration
def test_cli_ingest_then_ask_markdown(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_path = _write_markdown_fixture(tmp_path / "client-cli.md")

    ingest = runner.invoke(
        app,
        [
            "ingest",
            str(source_path),
            "--source-kind",
            "markdown",
            "--storage-path",
            str(workspace),
            "--preset",
            "academic_paper",
        ],
    )

    assert ingest.exit_code == 0, ingest.stdout
    ingest_payload = json.loads(ingest.stdout)
    ask = runner.invoke(
        app,
        [
            "ask",
            "What does the CLI build by default?",
            "--document-id",
            ingest_payload["document_id"],
            "--storage-path",
            str(workspace),
        ],
    )

    assert ask.exit_code == 0, ask.stdout
    ask_payload = json.loads(ask.stdout)
    assert ask_payload["answer"]
