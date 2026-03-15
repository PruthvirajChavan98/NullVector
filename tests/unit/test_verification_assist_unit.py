"""Unit tests for the opt-in LLM verification assistant."""

from __future__ import annotations

import json
from pathlib import Path

from nullvector.domain import (
    AnchorSource,
    HierarchyNode,
    HierarchyOrigin,
    LLMVerificationAssistRecord,
    NodeAnchor,
    PageSourceAnchor,
    PageSpan,
    TitleMatchTier,
    TreeSettings,
)
from nullvector.domain.tree import VerificationStatus
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    LiteLLMProviderConfig,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.llm.protocols import ProviderAdapter
from nullvector.llm.types import ProviderInvocationRequest, ProviderInvocationResult
from nullvector.tree.headings import PageArtifacts
from nullvector.tree.verify import LLMVerificationAssistant, verify_hierarchy


class CountingProviderAdapter:
    """Wrap a provider adapter and record each invoke call."""

    provider_name = "counting"

    def __init__(self, delegate: ProviderAdapter) -> None:
        self._delegate = delegate
        self.calls: list[str] = []

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        self.calls.append(request.operation_name)
        return self._delegate.invoke(request, config)


def make_gateway(
    tmp_path: Path,
    *,
    verdict: str,
    quotes: tuple[str, ...],
) -> tuple[GatewayService, CountingProviderAdapter]:
    delegate = NoopProviderAdapter(
        {
            "verify_heading_title": NoopScriptedResponse(
                output_json={
                    "verdict": verdict,
                    "rationale": "bounded evidence review",
                    "supporting_quotes": list(quotes),
                }
            )
        }
    )
    adapter = CountingProviderAdapter(delegate)
    gateway = GatewayService(
        GatewayConfig(
            provider=LiteLLMProviderConfig(model="test-model"),
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=adapter,
    )
    return gateway, adapter


def make_node(
    *,
    node_id: str,
    title: str,
    page_index: int,
) -> HierarchyNode:
    anchor = NodeAnchor(
        page=page_index,
        start_offset=0,
        end_offset=max(1, len(title)),
        anchor_text=title,
        anchor_source=AnchorSource.TEXT,
        occurrence_index=0,
    )
    return HierarchyNode(
        node_id=node_id,
        document_id="d" * 64,
        path=(title,),
        level=1,
        title=title,
        normalized_title=title.casefold(),
        page_span=PageSpan(start_page=page_index, end_page=page_index),
        heading_anchor=anchor,
        source_anchors=(
            PageSourceAnchor(
                page=page_index,
                start_offset=0,
                end_offset=max(1, len(title)),
                quote=title,
            ),
        ),
        origin=HierarchyOrigin.INFERRED,
        confidence=0.8,
    )


def test_verify_hierarchy_without_assistant_is_backward_compatible() -> None:
    node = make_node(node_id="n1", title="Missing Title", page_index=0)
    page = PageArtifacts(page_index=0, text="Unrelated\nNarrative\nContent", rawdict=None)

    verified_nodes, report = verify_hierarchy(
        document_id="d" * 64,
        tree_run_id="tree-run",
        page_count=1,
        nodes=(node,),
        pages=(page,),
        unassigned_spans=(),
        settings=TreeSettings(),
        verification_assistant=None,
    )

    assert report.status is VerificationStatus.FAILED
    assert verified_nodes[0].verification_match_tier is TitleMatchTier.NONE


def test_assistant_invoked_only_for_none_matches(tmp_path: Path) -> None:
    gateway, adapter = make_gateway(tmp_path, verdict="yes", quotes=("Evidence line",))
    assistant = LLMVerificationAssistant(gateway, artifact_root=str(tmp_path))
    pages = (
        PageArtifacts(page_index=0, text="Overview\nBody", rawdict=None),
        PageArtifacts(page_index=1, text="Control Valve Details\nBody", rawdict=None),
        PageArtifacts(page_index=2, text="Evidence line\nNarrative", rawdict=None),
    )
    nodes = (
        make_node(node_id="exact", title="Overview", page_index=0),
        make_node(node_id="token", title="Control Valve", page_index=1),
        make_node(node_id="none", title="Missing Title", page_index=2),
    )

    verified_nodes, report = verify_hierarchy(
        document_id="d" * 64,
        tree_run_id="tree-run",
        page_count=3,
        nodes=nodes,
        pages=pages,
        unassigned_spans=(),
        settings=TreeSettings(),
        verification_assistant=assistant,
    )

    assert adapter.calls == ["verify_heading_title"]
    assert [node.verification_match_tier for node in verified_nodes] == [
        TitleMatchTier.EXACT_NORMALIZED,
        TitleMatchTier.TOKEN_CONTAINMENT,
        TitleMatchTier.LLM_VERIFIED,
    ]
    assert report.status is VerificationStatus.PASSED


def test_grounded_positive_assist_is_accepted(tmp_path: Path) -> None:
    gateway, _ = make_gateway(tmp_path, verdict="yes", quotes=("Quoted evidence",))
    assistant = LLMVerificationAssistant(gateway, artifact_root=str(tmp_path))
    node = make_node(node_id="node-accepted", title="Missing Title", page_index=0)
    page = PageArtifacts(page_index=0, text="Quoted evidence\nNarrative", rawdict=None)

    match_tier, record = assistant.assist(node=node, page=page, settings=TreeSettings())

    assert match_tier is TitleMatchTier.LLM_VERIFIED
    assert record.accepted is True
    assert record.grounded_quotes == ("Quoted evidence",)


def test_positive_assist_with_ungrounded_quotes_is_rejected(tmp_path: Path) -> None:
    gateway, _ = make_gateway(tmp_path, verdict="yes", quotes=("Missing quote",))
    assistant = LLMVerificationAssistant(gateway, artifact_root=str(tmp_path))
    node = make_node(node_id="node-rejected", title="Missing Title", page_index=0)
    page = PageArtifacts(page_index=0, text="Actual page text\nNarrative", rawdict=None)

    match_tier, record = assistant.assist(node=node, page=page, settings=TreeSettings())

    assert match_tier is TitleMatchTier.NONE
    assert record.accepted is False
    assert record.ungrounded_quotes == ("Missing quote",)


def test_negative_verdict_keeps_node_failed(tmp_path: Path) -> None:
    gateway, _ = make_gateway(tmp_path, verdict="no", quotes=("Quoted evidence",))
    assistant = LLMVerificationAssistant(gateway, artifact_root=str(tmp_path))
    node = make_node(node_id="node-negative", title="Missing Title", page_index=0)
    page = PageArtifacts(page_index=0, text="Quoted evidence\nNarrative", rawdict=None)

    verified_nodes, report = verify_hierarchy(
        document_id="d" * 64,
        tree_run_id="tree-run",
        page_count=1,
        nodes=(node,),
        pages=(page,),
        unassigned_spans=(),
        settings=TreeSettings(),
        verification_assistant=assistant,
    )

    assert verified_nodes[0].verification_match_tier is TitleMatchTier.NONE
    assert report.status is VerificationStatus.FAILED


def test_assist_records_persist_replayably(tmp_path: Path) -> None:
    gateway, _ = make_gateway(tmp_path, verdict="yes", quotes=("Quoted evidence",))
    assistant = LLMVerificationAssistant(gateway, artifact_root=str(tmp_path))
    node = make_node(node_id="node-persisted", title="Missing Title", page_index=0)
    page = PageArtifacts(page_index=0, text="Quoted evidence\nNarrative", rawdict=None)

    _, record = assistant.assist(node=node, page=page, settings=TreeSettings())

    artifact_path = Path(assistant.artifact_path or "")
    assert artifact_path.exists()
    persisted = tuple(
        LLMVerificationAssistRecord.model_validate_json(json.dumps(item))
        for item in json.loads(artifact_path.read_text(encoding="utf-8"))
    )
    assert persisted == (record,)
