"""Integration coverage for the public NullVector client facade."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nullvector._client_utils import load_model_artifact, manifest_ref
from nullvector.client import NullVectorClient
from nullvector.domain.ledger import AcquisitionRunManifest
from nullvector.domain.retrieval import DocumentDescriptionManifest
from nullvector.domain.tree import TreeBuildManifest

_RUN_ID_PATTERN = re.compile(
    r"^(?P<prefix>.+)-(?P<token>[0-9a-f]{12})-(?P<stage>acquisition|tree|retrieval|description)$"
)


def _write_markdown_fixture(path: Path) -> Path:
    path.write_text(
        "\n".join(
            (
                "# Overview",
                "NullVector client ingest creates a queryable pipeline.",
                "",
                "## Details",
                "This section becomes the tree body and supports grounded retrieval.",
                "",
                "### Appendix",
                "Final stable notes for client QA coverage.",
            )
        ),
        encoding="utf-8",
    )
    return path


def _run_id_token(run_id: str) -> str:
    match = _RUN_ID_PATTERN.fullmatch(run_id)
    assert match is not None
    return match.group("token")


def _filesystem_manifest_run_id(path: str) -> str:
    return Path(path).parent.name


@pytest.mark.integration
def test_client_ingest_search_and_ask_markdown(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_path = _write_markdown_fixture(tmp_path / "client-flow.md")
    client = NullVectorClient(storage_path=workspace)

    result = client.ingest(source_path, source_kind="markdown", preset="general_document")
    hits = client.search("tree body", document_id=result.document_id)
    response = client.ask("What supports grounded retrieval?", document_id=result.document_id)

    assert hits
    assert response.answer
    assert result.retrieval_manifest_path.endswith("manifest.json")
    catalog = json.loads((workspace / ".nullvector" / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["documents"][result.document_id]["retrieval_manifest_path"] == (
        result.retrieval_manifest_path
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_client_async_ingest_and_ask_markdown(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_path = _write_markdown_fixture(tmp_path / "client-async.md")
    client = NullVectorClient(storage_path=workspace)

    result = await client.async_ingest(source_path, source_kind="markdown")
    response = await client.async_ask("What is in the appendix?", document_id=result.document_id)

    assert result.document_id
    assert response.answer


@pytest.mark.integration
def test_client_ingest_generates_distinct_auto_run_ids_per_call(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_path = _write_markdown_fixture(tmp_path / "client-repeat.md")
    client = NullVectorClient(storage_path=workspace)

    first = client.ingest(source_path, source_kind="markdown")
    second = client.ingest(source_path, source_kind="markdown")

    first_acquisition = load_model_artifact(AcquisitionRunManifest, first.acquisition_manifest_path)
    second_acquisition = load_model_artifact(
        AcquisitionRunManifest,
        second.acquisition_manifest_path,
    )
    first_tree = load_model_artifact(TreeBuildManifest, first.tree_manifest_path)
    second_tree = load_model_artifact(TreeBuildManifest, second.tree_manifest_path)
    first_retrieval_run_id = _filesystem_manifest_run_id(first.retrieval_manifest_path)
    second_retrieval_run_id = _filesystem_manifest_run_id(second.retrieval_manifest_path)

    assert first_acquisition.acquisition_run_id != second_acquisition.acquisition_run_id
    assert first_tree.tree_run_id != second_tree.tree_run_id
    assert first_retrieval_run_id != second_retrieval_run_id
    assert _run_id_token(first_acquisition.acquisition_run_id) == _run_id_token(
        first_tree.tree_run_id
    )
    assert _run_id_token(first_tree.tree_run_id) == _run_id_token(first_retrieval_run_id)
    assert _run_id_token(second_acquisition.acquisition_run_id) == _run_id_token(
        second_tree.tree_run_id
    )
    assert _run_id_token(second_tree.tree_run_id) == _run_id_token(second_retrieval_run_id)
    assert _run_id_token(first_acquisition.acquisition_run_id) != _run_id_token(
        second_acquisition.acquisition_run_id
    )


@pytest.mark.integration
def test_client_build_tree_and_description_generate_unique_omitted_ids(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_path = _write_markdown_fixture(tmp_path / "client-derived-repeat.md")
    client = NullVectorClient(storage_path=workspace)

    acquisition_manifest, acquisition_manifest_path = client.acquire(
        source_path,
        source_kind="markdown",
    )

    first_tree = client.build_tree(acquisition_manifest_path)
    second_tree = client.build_tree(acquisition_manifest_path)
    first_tree_manifest_path = manifest_ref(
        run_type="tree",
        run_id=first_tree.tree_run_id,
        document_id=first_tree.document_id,
        artifact_root=first_tree.artifact_root,
    )
    first_description = client.build_description(
        acquisition_manifest_path,
        first_tree_manifest_path,
    )
    second_description = client.build_description(
        acquisition_manifest_path,
        first_tree_manifest_path,
    )

    assert acquisition_manifest.acquisition_run_id != first_tree.tree_run_id
    assert first_tree.tree_run_id != second_tree.tree_run_id
    assert _run_id_token(first_tree.tree_run_id) != _run_id_token(second_tree.tree_run_id)
    assert isinstance(first_description, DocumentDescriptionManifest)
    assert first_description.description_run_id != second_description.description_run_id
    assert _run_id_token(first_description.description_run_id) != _run_id_token(
        second_description.description_run_id
    )
