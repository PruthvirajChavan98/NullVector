"""Document-description builder tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullvector.domain.common import PageSpan
from nullvector.domain.retrieval import (
    DocumentDescription,
    DocumentDescriptionMethod,
    DocumentDescriptionRequest,
    DocumentDescriptionSettings,
)
from nullvector.domain.tree import NodeCard, NodeSummary, NodeSummaryMethod
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.retrieval import DocumentDescriptionBuilder
from nullvector.retrieval.description import (
    _build_deterministic_description,
    _select_source_nodes,
    _SelectedSourceNode,
)

from .support import write_synthetic_bundle


def _make_card(
    *,
    node_id: str,
    path: tuple[str, ...],
    level: int,
    start_page: int,
    end_page: int,
) -> NodeCard:
    return NodeCard(
        node_id=node_id,
        document_id="d" * 64,
        path=path,
        level=level,
        title=path[-1],
        page_span=PageSpan(start_page=start_page, end_page=end_page),
    )


def _load_description(path: str) -> DocumentDescription:
    return DocumentDescription.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _make_gateway(
    tmp_path: Path,
    *,
    output_json: dict[str, object],
) -> GatewayService:
    return GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "document_description": NoopScriptedResponse(output_json=output_json),
            }
        ),
    )


def test_select_source_nodes_orders_root_then_first_level_then_summarized_leaves() -> None:
    node_cards = (
        _make_card(
            node_id="root",
            path=("Document",),
            level=1,
            start_page=0,
            end_page=9,
        ),
        _make_card(
            node_id="chapter-a",
            path=("Document", "Intro"),
            level=2,
            start_page=0,
            end_page=2,
        ),
        _make_card(
            node_id="chapter-b",
            path=("Document", "Appendix"),
            level=2,
            start_page=3,
            end_page=9,
        ),
        _make_card(
            node_id="leaf-long",
            path=("Document", "Appendix", "Deep Dive"),
            level=3,
            start_page=3,
            end_page=8,
        ),
        _make_card(
            node_id="leaf-short",
            path=("Document", "Intro", "Detail"),
            level=3,
            start_page=1,
            end_page=1,
        ),
    )
    node_summaries = (
        NodeSummary(
            node_id="leaf-short",
            summary="Short detail section.",
            keywords=("detail",),
            summary_method=NodeSummaryMethod.PASSTHROUGH,
            token_count=5,
            estimated_token_count=5,
            exact_token_count=5,
            tokenizer_identity="test-tokenizer",
        ),
        NodeSummary(
            node_id="leaf-long",
            summary="Long appendix deep dive.",
            keywords=("appendix",),
            summary_method=NodeSummaryMethod.PASSTHROUGH,
            token_count=6,
            estimated_token_count=6,
            exact_token_count=6,
            tokenizer_identity="test-tokenizer",
        ),
    )

    selected = _select_source_nodes(node_cards, node_summaries, max_source_nodes=4)

    assert tuple(source.node_id for source in selected) == (
        "root",
        "chapter-a",
        "chapter-b",
        "leaf-long",
    )


def test_build_deterministic_description_uses_titles_and_first_summary() -> None:
    description = _build_deterministic_description(
        (
            _SelectedSourceNode(
                node_id="root",
                title="Document",
                path=("Document",),
                page_span={"start_page": 0, "end_page": 9},
                summary_text=None,
                keywords=(),
                source_quotes=(),
            ),
            _SelectedSourceNode(
                node_id="appendix",
                title="Appendix A",
                path=("Document", "Appendix A"),
                page_span={"start_page": 1, "end_page": 1},
                summary_text="Appendix A summarizes the alpha and beta body lines.",
                keywords=("appendix", "alpha"),
                source_quotes=("Alpha body line",),
            ),
        )
    )

    assert "Document" in description
    assert "Appendix A" in description
    assert "Appendix A summarizes the alpha and beta body lines." in description


@pytest.mark.parametrize(
    ("prefer_node_summaries", "expected_method"),
    [
        (True, DocumentDescriptionMethod.LLM_FROM_SUMMARIES),
        (False, DocumentDescriptionMethod.LLM_FROM_NODE_CARDS),
    ],
)
def test_builder_builds_description_via_gateway(
    tmp_path: Path,
    prefer_node_summaries: bool,
    expected_method: DocumentDescriptionMethod,
) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    builder = DocumentDescriptionBuilder()
    gateway = _make_gateway(
        tmp_path,
        output_json={
            "description_text": "Synthetic appendix description.",
            "supporting_node_ids": ["node-appendix-a"],
        },
    )

    manifest = builder.build(
        DocumentDescriptionRequest(
            acquisition_manifest_path=str(bundle.acquisition_manifest_path),
            tree_manifest_path=str(bundle.tree_manifest_path),
            description_run_id=f"gateway-{prefer_node_summaries}",
            settings=DocumentDescriptionSettings(
                prefer_node_summaries=prefer_node_summaries,
            ),
        ),
        gateway=gateway,
    )

    description = _load_description(manifest.description_path)

    assert manifest.document_id == bundle.document_id
    assert description.description_text == "Synthetic appendix description."
    assert description.description_method is expected_method
    assert description.source_node_ids == ("node-appendix-a",)


def test_builder_falls_back_deterministically_without_gateway(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    builder = DocumentDescriptionBuilder()

    manifest = builder.build(
        DocumentDescriptionRequest(
            acquisition_manifest_path=str(bundle.acquisition_manifest_path),
            tree_manifest_path=str(bundle.tree_manifest_path),
            description_run_id="deterministic-description",
        )
    )

    description = _load_description(manifest.description_path)

    assert description.description_method is DocumentDescriptionMethod.DETERMINISTIC_FALLBACK
    assert "Appendix A" in description.description_text


def test_builder_rerun_returns_existing_manifest(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    builder = DocumentDescriptionBuilder()
    request = DocumentDescriptionRequest(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
        description_run_id="rerun-description",
    )

    first = builder.build(request)
    second = builder.build(request)

    assert second == first


def test_builder_fails_when_node_cards_and_summaries_are_missing(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest_payload = json.loads(bundle.tree_manifest_path.read_text(encoding="utf-8"))
    manifest_payload["node_cards_path"] = None
    manifest_payload["node_summaries_path"] = None
    broken_manifest_path = tmp_path / "broken-tree-manifest.json"
    broken_manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="node cards or node summaries"):
        DocumentDescriptionBuilder().build(
            DocumentDescriptionRequest(
                acquisition_manifest_path=str(bundle.acquisition_manifest_path),
                tree_manifest_path=str(broken_manifest_path),
                description_run_id="missing-artifacts",
            )
        )


def test_builder_requires_gateway_when_requested(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)

    with pytest.raises(ValueError, match="require_gateway=True"):
        DocumentDescriptionBuilder().build(
            DocumentDescriptionRequest(
                acquisition_manifest_path=str(bundle.acquisition_manifest_path),
                tree_manifest_path=str(bundle.tree_manifest_path),
                description_run_id="require-gateway",
                settings=DocumentDescriptionSettings(require_gateway=True),
            )
        )


def test_builder_rejects_unknown_supporting_node_ids(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    gateway = _make_gateway(
        tmp_path,
        output_json={
            "description_text": "Synthetic appendix description.",
            "supporting_node_ids": ["unknown-node"],
        },
    )

    with pytest.raises(ValueError, match="outside the selected source set"):
        DocumentDescriptionBuilder().build(
            DocumentDescriptionRequest(
                acquisition_manifest_path=str(bundle.acquisition_manifest_path),
                tree_manifest_path=str(bundle.tree_manifest_path),
                description_run_id="bad-supporting-ids",
            ),
            gateway=gateway,
        )
