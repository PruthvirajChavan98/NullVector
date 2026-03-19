"""Unit tests for bottom-up node summarization."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from nullvector.domain import (
    AnchorSource,
    HierarchyNode,
    HierarchyOrigin,
    NodeAnchor,
    NodeSummaryMethod,
    PageSourceAnchor,
    PageSpan,
)
from nullvector.llm import (
    GatewayAssuranceMode,
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    GatewaySuccess,
    GatewayUsage,
)
from nullvector.llm.prompts import SummarizationPromptResponse
from nullvector.llm.protocols import ProviderAdapter, StructuredLLMGateway
from nullvector.llm.types import (
    GatewayRequest,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderInvocationSuccess,
    StructuredOutputMode,
)
from nullvector.tree.headings import PageArtifacts
from nullvector.tree.summarize import NodeSummarizer


class CaptureSummarizationAdapter:
    """Provider adapter that records prompt payloads and returns scripted summaries."""

    provider_name = "capture"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        del config
        message_contents = tuple(message.content for message in request.messages)
        self.calls.append((request.operation_name, message_contents))
        summary = (
            "condensed child summary"
            if request.operation_name == "summarize_leaf_node"
            else "parent rollup summary"
        )
        return ProviderInvocationResult(
            success=ProviderInvocationSuccess(
                provider_name=self.provider_name,
                model_name=request.model_name,
                assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                structured_output_json={"summary": summary, "keywords": ["k1", "k2"]},
                usage=GatewayUsage(input_tokens=1, output_tokens=1, total_tokens=2),
                status_code=200,
            )
        )


class RecordingBatchGateway:
    """Gateway test double that records batched summarization requests."""

    def __init__(self) -> None:
        self.invoke_calls: list[str] = []
        self.batch_calls: list[tuple[tuple[str, ...], int | None]] = []

    def invoke(
        self,
        request: GatewayRequest[SummarizationPromptResponse],
    ) -> GatewaySuccess[SummarizationPromptResponse]:
        self.invoke_calls.append(request.operation_name)
        raise AssertionError("NodeSummarizer should use invoke_many for LLM summaries")

    def invoke_many(
        self,
        requests: tuple[GatewayRequest[SummarizationPromptResponse], ...],
        *,
        max_workers: int | None = None,
    ) -> tuple[GatewaySuccess[SummarizationPromptResponse], ...]:
        self.batch_calls.append(
            (tuple(request.operation_name for request in requests), max_workers)
        )
        responses: list[GatewaySuccess[SummarizationPromptResponse]] = []
        for index, request in enumerate(requests):
            summary = (
                f"leaf summary {index}"
                if request.operation_name == "summarize_leaf_node"
                else "parent rollup summary"
            )
            responses.append(
                GatewaySuccess(
                    request_id=f"batch-{index}",
                    operation_name=request.operation_name,
                    provider_name="recording-batch",
                    model_name="test-model",
                    assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
                    structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
                    output=SummarizationPromptResponse(summary=summary, keywords=("k1", "k2")),
                    attempts=(),
                    usage=GatewayUsage(input_tokens=1, output_tokens=1, total_tokens=2),
                    audit_path=f"/tmp/{request.operation_name}-{index}.json",
                )
            )
        return tuple(responses)


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
    start_offset: int = 0,
    end_offset: int | None = None,
    parent_id: str | None = None,
    path: tuple[str, ...] | None = None,
    level: int = 1,
    span_end_page: int | None = None,
) -> HierarchyNode:
    end = end_offset if end_offset is not None else start_offset + len(title)
    return HierarchyNode(
        node_id=node_id,
        document_id="d" * 64,
        parent_id=parent_id,
        path=path or (title,),
        level=level,
        title=title,
        normalized_title=title.casefold(),
        page_span=PageSpan(start_page=page_index, end_page=span_end_page or page_index),
        heading_anchor=NodeAnchor(
            page=page_index,
            start_offset=start_offset,
            end_offset=end,
            anchor_text=title,
            anchor_source=AnchorSource.TEXT,
            occurrence_index=0,
        ),
        source_anchors=(
            PageSourceAnchor(
                page=page_index,
                start_offset=start_offset,
                end_offset=end,
                quote=title,
            ),
        ),
        origin=HierarchyOrigin.INFERRED,
        confidence=0.8,
    )


def test_leaf_passthrough_avoids_gateway_calls(tmp_path: Path) -> None:
    adapter = CaptureSummarizationAdapter()
    summarizer = NodeSummarizer(make_gateway(tmp_path, adapter))
    node = make_node(node_id="leaf", title="Leaf", page_index=0)
    pages = (PageArtifacts(page_index=0, text="Leaf\nshort body", rawdict=None),)

    _, node_cards, summaries = summarizer.summarize(nodes=(node,), pages=pages)

    assert adapter.calls == []
    assert summaries[0].summary_method is NodeSummaryMethod.PASSTHROUGH
    assert summaries[0].tokenizer_identity == "heuristic"
    assert summaries[0].exact_token_count is None
    assert node_cards[0].summary == "Leaf\nshort body"


def test_long_leaf_uses_llm_leaf_summarization(tmp_path: Path) -> None:
    adapter = CaptureSummarizationAdapter()
    summarizer = NodeSummarizer(make_gateway(tmp_path, adapter))
    long_text = " ".join(["alpha"] * 180)
    node = make_node(node_id="leaf", title="Leaf", page_index=0)
    pages = (PageArtifacts(page_index=0, text=f"Leaf\n{long_text}", rawdict=None),)

    _, node_cards, summaries = summarizer.summarize(nodes=(node,), pages=pages)

    assert [call[0] for call in adapter.calls] == ["summarize_leaf_node"]
    assert summaries[0].summary_method is NodeSummaryMethod.LLM_LEAF
    assert summaries[0].gateway_provider_name == "capture"
    assert summaries[0].gateway_assurance_mode == "transport_compatible"
    assert summaries[0].gateway_usage is not None
    assert summaries[0].gateway_usage.total_tokens == 2
    assert node_cards[0].summary == "condensed child summary"
    assert node_cards[0].keywords == ("k1", "k2")


def test_parent_summarization_uses_prefix_text_and_child_summaries(tmp_path: Path) -> None:
    adapter = CaptureSummarizationAdapter()
    summarizer = NodeSummarizer(make_gateway(tmp_path, adapter))
    parent = make_node(
        node_id="parent",
        title="Parent",
        page_index=0,
        start_offset=0,
        end_offset=6,
        path=("Parent",),
        span_end_page=1,
    )
    child = make_node(
        node_id="child",
        title="Child",
        page_index=1,
        parent_id="parent",
        path=("Parent", "Child"),
        level=2,
    )
    long_child_text = " ".join(["RAW_CHILD_PHRASE"] * 180)
    pages = (
        PageArtifacts(page_index=0, text="Parent prefix only context.", rawdict=None),
        PageArtifacts(page_index=1, text=f"Child\n{long_child_text}", rawdict=None),
    )

    _, node_cards, summaries = summarizer.summarize(nodes=(parent, child), pages=pages)

    assert [call[0] for call in adapter.calls] == [
        "summarize_leaf_node",
        "summarize_parent_node",
    ]
    parent_prompt = adapter.calls[-1][1][-1]
    assert "condensed child summary" in parent_prompt
    assert "prefix only context." in parent_prompt
    assert "RAW_CHILD_PHRASE RAW_CHILD_PHRASE RAW_CHILD_PHRASE" not in parent_prompt
    assert summaries[0].summary_method is NodeSummaryMethod.LLM_PARENT
    assert summaries[0].tokenizer_identity == "heuristic"
    assert node_cards[0].summary == "parent rollup summary"


def test_bottom_up_ordering_is_deterministic(tmp_path: Path) -> None:
    adapter = CaptureSummarizationAdapter()
    summarizer = NodeSummarizer(make_gateway(tmp_path, adapter))
    parent = make_node(node_id="p", title="Parent", page_index=0, span_end_page=1)
    child = make_node(
        node_id="c",
        title="Child",
        page_index=1,
        parent_id="p",
        path=("Parent", "Child"),
        level=2,
    )
    pages = (
        PageArtifacts(page_index=0, text="Parent prefix", rawdict=None),
        PageArtifacts(page_index=1, text="Child\n" + " ".join(["beta"] * 180), rawdict=None),
    )

    summarizer.summarize(nodes=(parent, child), pages=pages)

    assert [call[0] for call in adapter.calls] == [
        "summarize_leaf_node",
        "summarize_parent_node",
    ]


def test_summarizer_batches_llm_requests_per_level() -> None:
    gateway = RecordingBatchGateway()
    summarizer = NodeSummarizer(cast(StructuredLLMGateway, gateway), max_workers=3)
    parent = make_node(node_id="parent", title="Parent", page_index=0, span_end_page=2)
    child_a = make_node(
        node_id="child-a",
        title="Child A",
        page_index=1,
        parent_id="parent",
        path=("Parent", "Child A"),
        level=2,
    )
    child_b = make_node(
        node_id="child-b",
        title="Child B",
        page_index=2,
        parent_id="parent",
        path=("Parent", "Child B"),
        level=2,
    )
    long_a = " ".join(["alpha"] * 180)
    long_b = " ".join(["beta"] * 180)
    pages = (
        PageArtifacts(page_index=0, text="Parent prefix context", rawdict=None),
        PageArtifacts(page_index=1, text=f"Child A\n{long_a}", rawdict=None),
        PageArtifacts(page_index=2, text=f"Child B\n{long_b}", rawdict=None),
    )

    _, node_cards, summaries = summarizer.summarize(nodes=(parent, child_a, child_b), pages=pages)

    assert gateway.invoke_calls == []
    assert gateway.batch_calls == [
        (("summarize_leaf_node", "summarize_leaf_node"), 3),
        (("summarize_parent_node",), 3),
    ]
    assert [summary.summary_method for summary in summaries] == [
        NodeSummaryMethod.LLM_PARENT,
        NodeSummaryMethod.LLM_LEAF,
        NodeSummaryMethod.LLM_LEAF,
    ]
    assert [card.summary for card in node_cards] == [
        "parent rollup summary",
        "leaf summary 0",
        "leaf summary 1",
    ]
