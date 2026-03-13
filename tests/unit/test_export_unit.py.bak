"""Unit tests for edge-only export helpers."""

from __future__ import annotations

import importlib
import types
from collections.abc import Callable

import pytest

from strataforge.domain import (
    ContentSpan,
    NodeCard,
    NodeOwnedSpan,
    NodeSummary,
    NodeSummaryMethod,
    PageSourceAnchor,
    PageSpan,
    StructuredRegionInsight,
    VisualEnrichmentAttachment,
)
from strataforge.export import (
    ExporterDependencyError,
    to_langchain_document,
    to_llamaindex_node,
)


def make_node_card() -> NodeCard:
    return NodeCard(
        node_id="node-001",
        document_id="d" * 64,
        path=("Overview",),
        level=1,
        title="Overview",
        page_span=PageSpan(start_page=0, end_page=1),
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=0,
                    start_offset=0,
                    end_page=1,
                    end_offset=10,
                ),
            ),
        ),
        source_anchors=(PageSourceAnchor(page=0, start_offset=0, end_offset=8, quote="Overview"),),
    )


def make_summary() -> NodeSummary:
    return NodeSummary(
        node_id="node-001",
        summary="summary text",
        keywords=("alpha",),
        summary_method=NodeSummaryMethod.LLM_PARENT,
        token_count=10,
        estimated_token_count=10,
        tokenizer_identity="heuristic",
    )


def make_attachment() -> VisualEnrichmentAttachment:
    return VisualEnrichmentAttachment(
        attachment_id="attach-001",
        document_id="d" * 64,
        node_id="node-001",
        region_id="region-001",
        provider_identity="noop",
        confidence=0.8,
        insight=StructuredRegionInsight(
            summary="visual summary",
            labels=("diagram",),
            attributes={"kind": "diagram"},
            confidence=0.8,
        ),
    )


def test_langchain_export_preserves_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDocument:
        def __init__(self, *, page_content: str, metadata: dict[str, object]) -> None:
            self.page_content = page_content
            self.metadata = metadata

    fake_module = types.SimpleNamespace(Document=FakeDocument)
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)

    document = to_langchain_document(
        make_node_card(),
        summary=make_summary(),
        attachments=(make_attachment(),),
    )

    assert document.page_content == "summary text"
    assert document.metadata["node_id"] == "node-001"
    assert document.metadata["summary_usage"]["tokenizer_identity"] == "heuristic"
    assert document.metadata["visual_enrichments"][0]["region_id"] == "region-001"


def test_llamaindex_export_preserves_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTextNode:
        def __init__(self, *, text: str, metadata: dict[str, object]) -> None:
            self.text = text
            self.metadata = metadata

    fake_module = types.SimpleNamespace(TextNode=FakeTextNode)
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module)

    node = to_llamaindex_node(
        make_node_card(),
        summary=make_summary(),
        attachments=(make_attachment(),),
    )

    assert node.text == "summary text"
    assert node.metadata["title"] == "Overview"
    assert node.metadata["visual_enrichments"][0]["summary"] == "visual summary"


@pytest.mark.parametrize("exporter", [to_langchain_document, to_llamaindex_node])
def test_exporters_raise_dependency_error_when_optional_dependency_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    exporter: Callable[..., object],
) -> None:
    def missing_import(name: str) -> object:
        del name
        raise ModuleNotFoundError("optional dependency missing")

    monkeypatch.setattr(importlib, "import_module", missing_import)

    with pytest.raises(ExporterDependencyError):
        exporter(make_node_card())
