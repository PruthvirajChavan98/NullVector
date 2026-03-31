"""Integration coverage for the public NullVector client facade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullvector.client import NullVectorClient


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
