"""Unit tests for typed hierarchy strategy orchestration."""

from __future__ import annotations

from typing import cast

from nullvector.domain import (
    HeadingCandidate,
    HierarchyStrategy,
    OutlineSource,
    OutlineTrustMode,
    TreeSettings,
)
from nullvector.tree.strategy import (
    StrategyAttemptResult,
    execute_hierarchy_strategy,
    select_hierarchy_strategy,
)


def make_attempt_result(strategy: HierarchyStrategy, accuracy: float) -> StrategyAttemptResult:
    return StrategyAttemptResult(
        strategy=strategy,
        accuracy=accuracy,
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
        committed_node_count=1,
        unassigned_span_count=0,
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
        settings=TreeSettings(max_strategy_cascade_depth=2),
        attempt_runner=lambda strategy, attempt_index: make_attempt_result(
            strategy,
            accuracy=0.0 if attempt_index == 1 else 0.9,
        ),
    )

    assert report.attempted_strategies == (
        HierarchyStrategy.INFERRED_WITH_LLM_ASSIST,
        HierarchyStrategy.INFERRED_DETERMINISTIC,
    )
    assert result.strategy is HierarchyStrategy.INFERRED_DETERMINISTIC
    assert report.cascade_depth == 1


def test_execute_hierarchy_strategy_uses_bounded_cascade() -> None:
    attempted: list[HierarchyStrategy] = []

    def runner(strategy: HierarchyStrategy, attempt_index: int) -> StrategyAttemptResult:
        attempted.append(strategy)
        accuracy = 0.2 if attempt_index == 1 else 0.8
        return make_attempt_result(strategy, accuracy)

    result, report = execute_hierarchy_strategy(
        current_trust_mode=OutlineTrustMode.OUTLINE_PRIMARY,
        selected_outline_source=OutlineSource.PYMUPDF,
        toc_candidates=(),
        gateway_available=False,
        settings=TreeSettings(strategy_accuracy_threshold=0.6, max_strategy_cascade_depth=2),
        attempt_runner=runner,
    )

    assert len(attempted) == 2
    assert report.accuracy_at_each_level == (0.2, 0.8)
    assert result.strategy is HierarchyStrategy.INFERRED_DETERMINISTIC


def test_execute_hierarchy_strategy_skips_llm_only_paths_without_gateway() -> None:
    result, report = execute_hierarchy_strategy(
        current_trust_mode=OutlineTrustMode.INFERRED_PRIMARY,
        selected_outline_source=OutlineSource.NONE,
        toc_candidates=(),
        gateway_available=False,
        settings=TreeSettings(max_strategy_cascade_depth=2),
        attempt_runner=lambda strategy, attempt_index: make_attempt_result(
            strategy,
            accuracy=1.0,
        ),
    )

    assert report.attempted_strategies == (HierarchyStrategy.INFERRED_DETERMINISTIC,)
    assert result.strategy is HierarchyStrategy.INFERRED_DETERMINISTIC


def test_execute_hierarchy_strategy_treats_cascade_depth_as_fallback_budget() -> None:
    attempted: list[HierarchyStrategy] = []

    def runner(strategy: HierarchyStrategy, attempt_index: int) -> StrategyAttemptResult:
        del attempt_index
        attempted.append(strategy)
        return make_attempt_result(strategy, 0.0)

    _, report = execute_hierarchy_strategy(
        current_trust_mode=OutlineTrustMode.INFERRED_PRIMARY,
        selected_outline_source=OutlineSource.NONE,
        toc_candidates=cast(tuple[HeadingCandidate, ...], ("placeholder",)),
        gateway_available=True,
        settings=TreeSettings(max_strategy_cascade_depth=2),
        attempt_runner=runner,
    )

    assert attempted == [
        HierarchyStrategy.TOC_DERIVED,
        HierarchyStrategy.INFERRED_WITH_LLM_ASSIST,
        HierarchyStrategy.INFERRED_DETERMINISTIC,
    ]
    assert report.cascade_depth == 2
