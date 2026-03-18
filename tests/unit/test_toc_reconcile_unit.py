"""Unit tests for deterministic TOC reconciliation helpers."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain import (
    AnchorSource,
    HeadingCandidate,
    HeadingScoreBreakdown,
    HeadingSourceKind,
    NodeAnchor,
    OutlineQualityReport,
    OutlineSource,
    OutlineTrustMode,
    TocDetectionMethod,
    TocDetectionResult,
    TocPageScore,
    TocParseMethod,
    TreeSettings,
)
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.llm.protocols import ProviderAdapter
from nullvector.llm.types import JSONValue, ProviderInvocationRequest, ProviderInvocationResult
from nullvector.tree.headings import PageArtifacts, normalized_title_key
from nullvector.tree.hierarchy import determine_outline_trust_mode, reconcile_heading_candidates
from nullvector.tree.toc_reconcile import TocReconciler


class CountingProviderAdapter:
    """Wrap a provider adapter and count operation invocations."""

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
    output_json: dict[str, JSONValue],
) -> tuple[GatewayService, CountingProviderAdapter]:
    delegate = NoopProviderAdapter({"toc_parse": NoopScriptedResponse(output_json=output_json)})
    adapter = CountingProviderAdapter(delegate)
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=adapter,
    )
    return gateway, adapter


def make_pages_with_offset() -> tuple[PageArtifacts, ...]:
    return (
        PageArtifacts(page_index=0, text="Cover Page", rawdict=None),
        PageArtifacts(page_index=1, text="Table of Contents\n...", rawdict=None),
        PageArtifacts(page_index=2, text="Preface\nFront matter.", rawdict=None),
        PageArtifacts(page_index=3, text="Introduction\nDocument starts here.", rawdict=None),
        PageArtifacts(page_index=4, text="Scope\nApplicable boundaries.", rawdict=None),
        PageArtifacts(page_index=5, text="Safety\nOperational limits.", rawdict=None),
        PageArtifacts(page_index=6, text="Operations\nDetailed steps.", rawdict=None),
    )


def make_toc_result(toc_content: str) -> TocDetectionResult:
    return TocDetectionResult(
        toc_page_indices=(1,),
        toc_content=toc_content,
        detection_method=TocDetectionMethod.DETERMINISTIC,
        page_scores=(
            TocPageScore(
                page_index=1,
                pattern_match_count=3,
                leader_dot_density=1.0,
                numbering_density=1.0,
                final_score=0.95,
                classified_as_toc=True,
                classification_reason=("detected",),
            ),
        ),
        has_page_numbers=True,
    )


def make_outline_candidate(title: str, page_index: int) -> HeadingCandidate:
    return HeadingCandidate(
        document_id="d" * 64,
        page_index=page_index,
        title=title,
        normalized_title=normalized_title_key(title),
        anchor=NodeAnchor(
            page=page_index,
            start_offset=0,
            end_offset=len(title),
            anchor_text=title,
            anchor_source=AnchorSource.TEXT,
            occurrence_index=0,
        ),
        source_kind=HeadingSourceKind.OUTLINE,
        level_hint=1,
        outline_level_hint=1,
        score_breakdown=HeadingScoreBreakdown(toc_overlap_signal=40, final_score=100),
        keep=True,
        high_confidence=True,
    )


def test_deterministic_toc_parsing_avoids_gateway(tmp_path: Path) -> None:
    gateway, adapter = make_gateway(
        tmp_path,
        output_json={
            "entries": [
                {"structure": "1", "title": "Wrong", "page_number": 9},
            ]
        },
    )
    reconciler = TocReconciler(TreeSettings(), gateway=gateway)
    toc_result = make_toc_result(
        "\n".join(
            (
                "1 Introduction ........ 1",
                "1.1 Scope ........ 2",
                "Chapter 2: Safety ........ 3",
                "Operations      4",
            )
        )
    )

    result = reconciler.reconcile(
        document_id="d" * 64,
        pages=make_pages_with_offset(),
        toc_result=toc_result,
        artifact_root=str(tmp_path),
    )

    assert adapter.calls == []
    assert result.parse_method is TocParseMethod.DETERMINISTIC
    assert [entry.title for entry in result.parsed_entries[:3]] == [
        "Introduction",
        "Scope",
        "Safety",
    ]


def test_offset_reconciliation_uses_mode_of_logical_to_physical_pairs() -> None:
    reconciler = TocReconciler(TreeSettings())
    toc_result = make_toc_result(
        "\n".join(
            (
                "1 Introduction ........ 1",
                "1.1 Scope ........ 2",
                "2 Safety ........ 3",
                "3 Operations ........ 4",
            )
        )
    )

    result = reconciler.reconcile(
        document_id="d" * 64,
        pages=make_pages_with_offset(),
        toc_result=toc_result,
    )

    assert result.offset == 2
    assert result.offset_confidence > 0
    assert [candidate.page_index for candidate in result.reconciled_candidates] == [3, 4, 5, 6]


def test_llm_assisted_parsing_fallback_keeps_offset_deterministic(tmp_path: Path) -> None:
    gateway, adapter = make_gateway(
        tmp_path,
        output_json={
            "entries": [
                {"structure": "1", "title": "Introduction", "page_number": 1},
                {"structure": "1.1", "title": "Scope", "page_number": 2},
                {"structure": "2", "title": "Safety", "page_number": 3},
            ]
        },
    )
    reconciler = TocReconciler(TreeSettings(), gateway=gateway)
    toc_result = make_toc_result(
        "\n".join(
            (
                "Intro => page one",
                "Scope => page two",
                "Safety => page three",
            )
        )
    )

    result = reconciler.reconcile(
        document_id="d" * 64,
        pages=make_pages_with_offset(),
        toc_result=toc_result,
    )

    assert adapter.calls == ["toc_parse"]
    assert result.parse_method is TocParseMethod.LLM_ASSISTED
    assert result.offset == 2
    assert [candidate.title for candidate in result.reconciled_candidates] == [
        "Introduction",
        "Scope",
        "Safety",
    ]


def test_reconciliation_returns_no_offset_when_titles_cannot_be_anchored() -> None:
    reconciler = TocReconciler(TreeSettings())
    toc_result = make_toc_result(
        "\n".join(
            (
                "1 Missing Section ........ 1",
                "2 Another Missing Section ........ 2",
                "3 Still Missing ........ 3",
            )
        )
    )

    result = reconciler.reconcile(
        document_id="d" * 64,
        pages=make_pages_with_offset(),
        toc_result=toc_result,
    )

    assert result.offset is None
    assert result.offset_confidence == 0.0
    assert result.reconciled_candidates == ()


def test_hierarchy_hooks_remain_backward_compatible_without_toc_candidates() -> None:
    outline_candidates = (make_outline_candidate("Overview", 0),)
    inferred_candidates = (make_outline_candidate("Overview", 0),)
    reports = (
        OutlineQualityReport(
            source=OutlineSource.PYMUPDF,
            entry_count=1,
            null_destination_count=0,
            empty_title_count=0,
            non_monotonic_count=0,
            invalid_level_count=0,
            max_depth=1,
            score=100,
        ),
    )
    settings = TreeSettings()

    trust_without_toc = determine_outline_trust_mode(
        selected_source=OutlineSource.PYMUPDF,
        outline_reports=reports,
        outline_candidates=outline_candidates,
        inferred_candidates=inferred_candidates,
        settings=settings,
    )
    trust_with_empty_toc = determine_outline_trust_mode(
        selected_source=OutlineSource.PYMUPDF,
        outline_reports=reports,
        outline_candidates=outline_candidates,
        inferred_candidates=inferred_candidates,
        toc_candidates=(),
        settings=settings,
    )
    assert trust_without_toc is trust_with_empty_toc

    selected_without_toc = reconcile_heading_candidates(
        outline_candidates=outline_candidates,
        inferred_candidates=inferred_candidates,
        trust_mode=trust_without_toc,
        settings=settings,
    )
    selected_with_empty_toc = reconcile_heading_candidates(
        outline_candidates=outline_candidates,
        inferred_candidates=inferred_candidates,
        trust_mode=trust_with_empty_toc,
        toc_candidates=(),
        settings=settings,
    )

    assert trust_without_toc is OutlineTrustMode.OUTLINE_PRIMARY
    assert selected_without_toc == selected_with_empty_toc
