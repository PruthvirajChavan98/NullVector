"""Unit tests for deterministic-first large-node decomposition."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain import (
    AnchorSource,
    ContentSpan,
    HierarchyNode,
    HierarchyOrigin,
    NodeAnchor,
    NodeOwnedSpan,
    PageSourceAnchor,
    PageSpan,
    TreeSettings,
)
from nullvector.domain.models import VerificationStatus
from nullvector.llm import (
    GatewayAssuranceMode,
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    GatewayUsage,
    LiteLLMProviderConfig,
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
from nullvector.tree.headings import PageArtifacts, split_text_lines_with_offsets
from nullvector.tree.verify import determine_title_match_tier, verify_hierarchy


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
            provider=LiteLLMProviderConfig(model="test-model"),
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
        heading_anchor=NodeAnchor(
            page=page_index,
            start_offset=0,
            end_offset=len(title),
            anchor_text=title,
            anchor_source=AnchorSource.TEXT,
            occurrence_index=0,
        ),
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


def test_deterministic_large_node_decomposition_creates_children(tmp_path: Path) -> None:
    parent = make_node(node_id="root", title="Root", page_index=0, span_end_page=3)
    pages = (
        PageArtifacts(page_index=0, text="Root\nintro body\ncontext", rawdict=None),
        PageArtifacts(page_index=1, text="SECTION ALPHA\nalpha body", rawdict=None),
        PageArtifacts(page_index=2, text="SECTION BETA\nbeta body", rawdict=None),
        PageArtifacts(page_index=3, text="SECTION GAMMA\ngamma body", rawdict=None),
    )
    decomposer = NodeDecomposer(TreeSettings(max_pages_per_leaf_node=2))

    nodes, report = decomposer.decompose(
        nodes=(parent,),
        pages=pages,
        tree_run_id="tree-run",
        artifact_root=str(tmp_path),
    )

    children = [node for node in nodes if node.parent_id == "root"]

    assert report.decomposition_method.value == "deterministic"
    assert report.decomposed_node_ids == ("root",)
    assert report.new_child_count == 3
    assert report.empty_parent_count == 0
    assert report.depth == 1
    assert report.tokenizer_identity == "heuristic"
    assert decomposer.artifact_path is not None
    assert Path(decomposer.artifact_path).exists()
    assert [child.title for child in children] == [
        "SECTION ALPHA",
        "SECTION BETA",
        "SECTION GAMMA",
    ]
    root = next(node for node in nodes if node.node_id == "root")
    assert root.page_span == PageSpan(start_page=0, end_page=3)
    assert root.owned_spans[0].span == ContentSpan(
        start_page=0,
        start_offset=0,
        end_page=1,
        end_offset=0,
    )
    assert children[0].owned_spans[0].span == ContentSpan(
        start_page=1,
        start_offset=0,
        end_page=2,
        end_offset=0,
    )


def test_llm_fallback_decomposition_is_bounded_and_auditable(tmp_path: Path) -> None:
    parent = make_node(node_id="root", title="Root", page_index=0, span_end_page=2)
    pages = (
        PageArtifacts(page_index=0, text="Root\nintro body\ncontext", rawdict=None),
        PageArtifacts(page_index=1, text="subsection a.\nalpha body", rawdict=None),
        PageArtifacts(page_index=2, text="subsection b.\nbeta body", rawdict=None),
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


def test_decomposition_depth_limit_stops_recursive_expansion() -> None:
    parent = make_node(node_id="root", title="Root", page_index=0, span_end_page=6)
    pages = (
        PageArtifacts(page_index=0, text="Root\nintro", rawdict=None),
        PageArtifacts(page_index=1, text="SECTION A\nbody", rawdict=None),
        PageArtifacts(page_index=2, text="SUBSECTION A1\nbody", rawdict=None),
        PageArtifacts(page_index=3, text="SUBSECTION A2\nbody", rawdict=None),
        PageArtifacts(page_index=4, text="SECTION B\nbody", rawdict=None),
        PageArtifacts(page_index=5, text="SUBSECTION B1\nbody", rawdict=None),
        PageArtifacts(page_index=6, text="SUBSECTION B2\nbody", rawdict=None),
    )
    decomposer = NodeDecomposer(TreeSettings(max_pages_per_leaf_node=1, max_decomposition_depth=1))

    nodes, report = decomposer.decompose(nodes=(parent,), pages=pages, tree_run_id="tree-run")

    assert report.depth == 1
    assert not any(node.level >= 3 for node in nodes)


def test_parent_span_truncates_to_prefix_before_first_child() -> None:
    parent = make_node(node_id="root", title="Root", page_index=0, span_end_page=0)
    pages = (
        PageArtifacts(
            page_index=0,
            text="Root\nSECTION A\nbody\nSECTION B\nbody",
            rawdict=None,
        ),
    )
    decomposer = NodeDecomposer(TreeSettings(max_pages_per_leaf_node=1, max_tokens_per_leaf_node=1))

    nodes, _ = decomposer.decompose(nodes=(parent,), pages=pages, tree_run_id="tree-run")
    truncated_parent = next(node for node in nodes if node.node_id == "root")
    children = [node for node in nodes if node.parent_id == "root"]

    assert truncated_parent.page_span == PageSpan(start_page=0, end_page=0)
    assert truncated_parent.owned_spans[0].span.start_offset == 0
    assert truncated_parent.owned_spans[0].span.end_page == 0
    assert (
        truncated_parent.owned_spans[0].span.end_offset == children[0].heading_anchor.start_offset
    )
    assert children[0].owned_spans[0].span == ContentSpan(
        start_page=0,
        start_offset=children[0].heading_anchor.start_offset,
        end_page=0,
        end_offset=children[1].heading_anchor.start_offset,
    )


def test_verify_hierarchy_uses_owned_span_containment_when_present() -> None:
    parent = make_node(
        node_id="root",
        title="Root",
        page_index=0,
        span_end_page=0,
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=0,
                    start_offset=0,
                    end_page=0,
                    end_offset=20,
                ),
            ),
        ),
    )
    child = make_node(
        node_id="child",
        title="Child",
        page_index=0,
        span_end_page=0,
        level=2,
        parent_id="root",
        path=("Root", "Child"),
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=0,
                    start_offset=5,
                    end_page=0,
                    end_offset=15,
                ),
            ),
        ),
    )
    page = PageArtifacts(page_index=0, text="Root\nChild\nBody", rawdict=None)

    _, report = verify_hierarchy(
        document_id=parent.document_id,
        tree_run_id="tree-run",
        page_count=1,
        nodes=(parent, child),
        pages=(page,),
        unassigned_spans=(),
        settings=TreeSettings(),
    )

    assert report.status is VerificationStatus.PASSED


def test_verify_hierarchy_rejects_child_outside_parent_owned_span() -> None:
    parent = make_node(
        node_id="root",
        title="Root",
        page_index=0,
        span_end_page=0,
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=0,
                    start_offset=0,
                    end_page=0,
                    end_offset=10,
                ),
            ),
        ),
    )
    child = make_node(
        node_id="child",
        title="Child",
        page_index=0,
        span_end_page=0,
        level=2,
        parent_id="root",
        path=("Root", "Child"),
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=0,
                    start_offset=5,
                    end_page=0,
                    end_offset=15,
                ),
            ),
        ),
    )
    page = PageArtifacts(page_index=0, text="Root\nChild\nBody", rawdict=None)

    _, report = verify_hierarchy(
        document_id=parent.document_id,
        tree_run_id="tree-run",
        page_count=1,
        nodes=(parent, child),
        pages=(page,),
        unassigned_spans=(),
        settings=TreeSettings(),
    )

    assert report.status is VerificationStatus.FAILED
    assert any(
        issue.message == "child node owned span must remain inside its parent owned span"
        for result in report.node_results
        for issue in result.issues
    )


def test_verify_hierarchy_accepts_child_owned_span_inside_any_parent_owned_span() -> None:
    parent = make_node(
        node_id="root",
        title="Root",
        page_index=0,
        span_end_page=1,
        owned_spans=(
            NodeOwnedSpan(
                kind="prefix",
                span=ContentSpan(
                    start_page=0,
                    start_offset=0,
                    end_page=0,
                    end_offset=10,
                ),
            ),
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=1,
                    start_offset=0,
                    end_page=1,
                    end_offset=20,
                ),
            ),
        ),
    )
    child = make_node(
        node_id="child",
        title="Child",
        page_index=1,
        span_end_page=1,
        level=2,
        parent_id="root",
        path=("Root", "Child"),
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=1,
                    start_offset=5,
                    end_page=1,
                    end_offset=15,
                ),
            ),
        ),
    )
    pages = (
        PageArtifacts(page_index=0, text="Root\nBody", rawdict=None),
        PageArtifacts(page_index=1, text="Child\nBody", rawdict=None),
    )

    _, report = verify_hierarchy(
        document_id=parent.document_id,
        tree_run_id="tree-run",
        page_count=2,
        nodes=(parent, child),
        pages=pages,
        unassigned_spans=(),
        settings=TreeSettings(),
    )

    assert report.status is VerificationStatus.PASSED


def test_mid_page_verification_fallback_accepts_local_anchor_window() -> None:
    page_text = "\n".join(
        [
            "Document Header",
            "Intro line",
            "Body line one",
            "Body line two",
            "Mid Section",
            "supporting detail",
        ]
    )
    page = PageArtifacts(page_index=0, text=page_text, rawdict=None)
    line = split_text_lines_with_offsets(page_text, 0)[4]
    node = HierarchyNode(
        node_id="mid",
        document_id="d" * 64,
        path=("Root", "Mid Section"),
        parent_id=None,
        level=2,
        title="Mid Section",
        normalized_title="mid section",
        page_span=PageSpan(start_page=0, end_page=0),
        heading_anchor=NodeAnchor(
            page=0,
            start_offset=line.start_offset,
            end_offset=line.end_offset,
            anchor_text=line.text,
            anchor_source=AnchorSource.TEXT,
            occurrence_index=line.occurrence_index,
        ),
        source_anchors=(
            PageSourceAnchor(
                page=0,
                start_offset=line.start_offset,
                end_offset=line.end_offset,
                quote=line.text,
            ),
        ),
        origin=HierarchyOrigin.INFERRED,
        confidence=0.8,
    )
    settings = TreeSettings(top_of_page_line_limit=3)

    assert determine_title_match_tier(node.title, page, settings).value == "none"

    verified_nodes, report = verify_hierarchy(
        document_id=node.document_id,
        tree_run_id="tree-run",
        page_count=1,
        nodes=(node,),
        pages=(page,),
        unassigned_spans=(),
        settings=settings,
    )

    assert report.status is VerificationStatus.PASSED
    assert report.node_results[0].status is VerificationStatus.PASSED
    assert verified_nodes[0].verification_match_tier.value == "exact_normalized"
