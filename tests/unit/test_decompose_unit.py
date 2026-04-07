"""Unit tests for deterministic-first large-node decomposition."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain import (
    HierarchyNode,
    HierarchyOrigin,
    NodeOwnedSpan,
    PageSourceAnchor,
    PageSpan,
    TreeSettings,
)
from nullvector.llm import (
    GatewayAssuranceMode,
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    GatewayUsage,
)
from nullvector.llm.protocols import ProviderAdapter
from nullvector.llm.types import (
    JSONValue,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    StructuredOutputMode,
)
from nullvector.tree.decompose import NodeDecomposer
from nullvector.tree.page_data import PageData as PageArtifacts


class CaptureDecompositionAdapter:
    """Provider adapter that records decomposition calls and returns scripted boundaries."""

    provider_name = "capture"

    def __init__(self, output_json: dict[str, JSONValue]) -> None:
        self.calls: list[str] = []
        self._output_json = output_json

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        del config
        self.calls.append(request.operation_name)
        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name=self.provider_name,
                model_name=request.model_name,
                assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                structured_output_json=self._output_json,
                usage=GatewayUsage(input_tokens=1, output_tokens=1, total_tokens=2),
                status_code=200,
            )
        )


def make_gateway(tmp_path: Path, adapter: ProviderAdapter) -> GatewayService:
    return GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=adapter,
    )


def make_node(
    *,
    node_id: str,
    title: str,
    page_index: int,
    span_end_page: int,
    level: int = 1,
    parent_id: str | None = None,
    path: tuple[str, ...] | None = None,
    owned_spans: tuple[NodeOwnedSpan, ...] = (),
) -> HierarchyNode:
    return HierarchyNode(
        node_id=node_id,
        document_id="d" * 64,
        parent_id=parent_id,
        path=path or (title,),
        level=level,
        title=title,
        normalized_title=title.casefold(),
        page_span=PageSpan(start_page=page_index, end_page=span_end_page),
        owned_spans=owned_spans,
        source_anchors=(
            PageSourceAnchor(
                page=page_index,
                start_offset=0,
                end_offset=len(title),
                quote=title,
            ),
        ),
        origin=HierarchyOrigin.OUTLINE,
        confidence=0.9,
    )


def test_llm_fallback_decomposition_is_bounded_and_auditable(tmp_path: Path) -> None:
    parent = make_node(node_id="root", title="Root", page_index=0, span_end_page=2)
    pages = (
        PageArtifacts(page_index=0, text="Root\nintro body\ncontext"),
        PageArtifacts(page_index=1, text="subsection a.\nalpha body"),
        PageArtifacts(page_index=2, text="subsection b.\nbeta body"),
    )
    adapter = CaptureDecompositionAdapter(
        {
            "entries": [
                {"title": "subsection a.", "page_index": 1},
                {"title": "subsection b.", "page_index": 2},
            ]
        }
    )
    decomposer = NodeDecomposer(
        TreeSettings(max_pages_per_leaf_node=1, max_decomposition_depth=1),
        gateway=make_gateway(tmp_path, adapter),
    )

    nodes, report = decomposer.decompose(nodes=(parent,), pages=pages, tree_run_id="tree-run")

    children = [node for node in nodes if node.parent_id == "root"]

    assert adapter.calls == ["decompose_large_node"]
    assert report.decomposition_method.value == "llm_assisted"
    assert report.new_child_count == 2
    assert report.gateway_provider_name == "capture"
    assert report.gateway_assurance_mode == "transport_compatible"
    assert report.gateway_usage is not None
    assert report.gateway_usage.total_tokens == 2
    assert [child.title for child in children] == ["subsection a.", "subsection b."]
