#!/usr/bin/env python3
"""Execute the canonical StrataForge progress notebook deterministically."""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat
from nbclient import NotebookClient


def sanitize_notebook(notebook: nbformat.NotebookNode) -> None:
    """Remove saved execution state so stale outputs cannot leak into reruns."""

    for cell in notebook.cells:
        if cell.get("cell_type") != "code":
            continue
        cell["execution_count"] = None
        cell["outputs"] = []


def execute_notebook(notebook_path: Path, output_path: Path) -> Path:
    """Execute a notebook and persist an executed copy under notebook-local artifacts."""

    notebook = nbformat.read(notebook_path, as_version=4)
    sanitize_notebook(notebook)
    repo_root = notebook_path.resolve().parents[1]
    client = NotebookClient(
        notebook,
        timeout=120,
        kernel_name="python3",
        resources={"metadata": {"path": str(repo_root)}},
    )
    client.execute()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, output_path)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--notebook",
        type=Path,
        default=Path("notebooks/progress.ipynb"),
        help="Notebook path relative to the repository root.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("notebooks/_artifacts/progress.executed.ipynb"),
        help="Executed notebook output path relative to the repository root.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    execute_notebook(args.notebook.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
