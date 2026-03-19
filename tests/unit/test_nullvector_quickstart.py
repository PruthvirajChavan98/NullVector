"""Unit coverage for the offline quickstart CLI helpers."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def load_quickstart_module() -> ModuleType:
    """Load the repo-level quickstart script as a testable Python module."""

    script_path = Path("scripts/nullvector_quickstart.py").resolve()
    spec = importlib.util.spec_from_file_location("nullvector_quickstart", script_path)
    if spec is None or spec.loader is None:
        pytest.fail("failed to load scripts/nullvector_quickstart.py as a module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_infer_source_kind_from_supported_extensions() -> None:
    module = load_quickstart_module()

    assert module.infer_source_kind("report.pdf", None).value == "pdf"
    assert module.infer_source_kind("notes.md", None).value == "markdown"
    assert module.infer_source_kind("guide.markdown", None).value == "markdown"


def test_default_run_id_uses_normalized_source_stem() -> None:
    module = load_quickstart_module()

    assert module.default_run_id("Q1 Revenue Deck!!.pdf", "tree") == "q1-revenue-deck-tree"


def test_validate_args_rejects_cross_flag_mismatches() -> None:
    module = load_quickstart_module()
    args = argparse.Namespace(
        source_path="report.pdf",
        source_kind=None,
        acquisition_run_id=None,
        tree_run_id=None,
        build_retrieval=False,
        retrieval_run_id="custom-retrieval",
        storage_backend="filesystem",
        artifact_root=None,
        pg_conninfo=None,
        pg_schema=None,
        print_tree_summary=False,
    )

    with pytest.raises(ValueError, match="--retrieval-run-id requires --build-retrieval"):
        module.validate_args(args)


def test_build_storage_config_requires_conninfo_for_postgres() -> None:
    module = load_quickstart_module()
    args = argparse.Namespace(
        storage_backend="postgres",
        pg_conninfo=None,
        pg_schema="tenant_01",
    )

    with pytest.raises(
        ValueError,
        match="--pg-conninfo is required when --storage-backend=postgres",
    ):
        module.build_storage_config(args)


def test_format_summary_is_stable_pretty_json() -> None:
    module = load_quickstart_module()

    formatted = module.format_summary(
        {
            "tree": {"committed_node_count": 2, "run_id": "demo-tree"},
            "acquisition": {"page_count": 1, "run_id": "demo-acquisition"},
        }
    )

    assert formatted == (
        "{\n"
        '  "acquisition": {\n'
        '    "page_count": 1,\n'
        '    "run_id": "demo-acquisition"\n'
        "  },\n"
        '  "tree": {\n'
        '    "committed_node_count": 2,\n'
        '    "run_id": "demo-tree"\n'
        "  }\n"
        "}"
    )
