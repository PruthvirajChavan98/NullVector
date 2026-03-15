"""Unit tests for typed hierarchy strategy orchestration."""

from __future__ import annotations

from typing import cast

from nullvector.domain import (
    HeadingCandidate,
    HierarchyStrategy,
    OutlineSource,
    OutlineTrustMode,
)
from nullvector.tree.strategy import (
    StrategyAttemptResult,
    execute_hierarchy_strategy,
    select_hierarchy_strategy,
)


def make_attempt_result(
    strategy: HierarchyStrategy,
    *,
    committed_node_count: int = 1,
    full_document_unassigned: bool = False,
) -> StrategyAttemptResult:
    return StrategyAttemptResult(
        strategy=strategy,
        artifact_root=f"/tmp/{strategy.value}",
        committed_hierarchy_path=f"/tmp/{strategy.value}/committed.json",
        node_cards_path=f"/tmp/{strategy.value}/node-cards.json",
        verification_report_path=f"/tmp/{strategy.value}/verify.json",
        headings_path=f"/tmp/{strategy.value}/headings.json",
        raw_hierarchy_path=f"/tmp/{strategy.value}/raw.json",
        repair_requests_path=f"/tmp/{strategy.value}/repair-requests.json",
        repair_decisions_path=f"/tmp/{strategy.value}/repair-decisions.json",
        repaired_hierarchy_path=f"/tmp/{strategy.value}/repaired.json",
        unassigned_spans_path=f"/tmp/{strategy.value}/unassigned.json",
        build_report_path=f"/tmp/{strategy.value}/build-report.json",
        committed_node_count=committed_node_count,
        unassigned_span_count=0,
        full_document_unassigned=full_document_unassigned,
    )


def test_select_hierarchy_strategy_preserves_outline_default_path() -> None:
    strategy, rationale = select_hierarchy_strategy(
        current_trust_mode=OutlineTrustMode.OUTLINE_PRIMARY,
        selected_outline_source=OutlineSource.PYMUPDF,
        toc_candidates=(),
        gateway_available=False,
    )

    assert strategy is HierarchyStrategy.OUTLINE_ONLY
    assert rationale.outline_available is True
    assert rationale.toc_available is False


def test_select_hierarchy_strategy_prefers_toc_when_outline_is_weak() -> None:
    strategy, _ = select_hierarchy_strategy(
        current_trust_mode=OutlineTrustMode.INFERRED_PRIMARY,
        selected_outline_source=OutlineSource.NONE,
        toc_candidates=cast(tuple[HeadingCandidate, ...], ("placeholder",)),
        gateway_available=False,
    )

    assert strategy is HierarchyStrategy.TOC_DERIVED


def test_select_hierarchy_strategy_exposes_llm_assist_when_gateway_exists() -> None:
    result, report = execute_hierarchy_strategy(
        current_trust_mode=OutlineTrustMode.INFERRED_PRIMARY,
        selected_outline_source=OutlineSource.NONE,
        toc_candidates=(),
        gateway_available=True,
        attempt_runner=lambda strategy, attempt_index: make_attempt_result(
            strategy,
            committed_node_count=0 if attempt_index == 1 else 1,
        ),
    )

    assert report.attempted_strategies == (
        HierarchyStrategy.INFERRED_WITH_LLM_ASSIST,
        HierarchyStrategy.INFERRED_DETERMINISTIC,
    )
    assert result.strategy is HierarchyStrategy.INFERRED_DETERMINISTIC
    assert report.fallback_reasons == ("inferred_with_llm_assist:zero_committed_nodes",)


def test_execute_hierarchy_strategy_falls_back_on_full_document_gap() -> None:
    attempted: list[HierarchyStrategy] = []

    def runner(strategy: HierarchyStrategy, attempt_index: int) -> StrategyAttemptResult:
        attempted.append(strategy)
        return make_attempt_result(
            strategy,
            full_document_unassigned=attempt_index == 1,
        )

    result, report = execute_hierarchy_strategy(
        current_trust_mode=OutlineTrustMode.OUTLINE_PRIMARY,
        selected_outline_source=OutlineSource.PYMUPDF,
        toc_candidates=(),
        gateway_available=False,
        attempt_runner=runner,
    )

    assert len(attempted) == 2
    assert report.fallback_reasons == ("outline_only:full_document_unassigned",)
    assert result.strategy is HierarchyStrategy.INFERRED_DETERMINISTIC


def test_execute_hierarchy_strategy_skips_llm_only_paths_without_gateway() -> None:
    result, report = execute_hierarchy_strategy(
        current_trust_mode=OutlineTrustMode.INFERRED_PRIMARY,
        selected_outline_source=OutlineSource.NONE,
        toc_candidates=(),
        gateway_available=False,
        attempt_runner=lambda strategy, attempt_index: make_attempt_result(
            strategy,
        ),
    )

    assert report.attempted_strategies == (HierarchyStrategy.INFERRED_DETERMINISTIC,)
    assert result.strategy is HierarchyStrategy.INFERRED_DETERMINISTIC


def test_execute_hierarchy_strategy_tries_remaining_paths_until_hard_failure_clears() -> None:
    attempted: list[HierarchyStrategy] = []

    def runner(strategy: HierarchyStrategy, attempt_index: int) -> StrategyAttemptResult:
        attempted.append(strategy)
        return make_attempt_result(strategy, committed_node_count=0 if attempt_index < 3 else 1)

    result, report = execute_hierarchy_strategy(
        current_trust_mode=OutlineTrustMode.INFERRED_PRIMARY,
        selected_outline_source=OutlineSource.NONE,
        toc_candidates=cast(tuple[HeadingCandidate, ...], ("placeholder",)),
        gateway_available=True,
        attempt_runner=runner,
    )

    assert attempted == [
        HierarchyStrategy.TOC_DERIVED,
        HierarchyStrategy.INFERRED_WITH_LLM_ASSIST,
        HierarchyStrategy.INFERRED_DETERMINISTIC,
    ]
    assert result.strategy is HierarchyStrategy.INFERRED_DETERMINISTIC
    assert report.fallback_reasons == (
        "toc_derived:zero_committed_nodes",
        "inferred_with_llm_assist:zero_committed_nodes",
    )
