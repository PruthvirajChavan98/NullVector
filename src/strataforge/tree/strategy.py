"""Typed strategy selection and bounded cascade orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from strataforge.domain.models import (
    HeadingCandidate,
    HierarchyStrategy,
    OutlineSource,
    OutlineTrustMode,
    StrategyExecutionReport,
    StrategyRationale,
    TreeSettings,
)


@dataclass(frozen=True)
class StrategyAttemptResult:
    """Internal result payload for a single strategy attempt."""

    strategy: HierarchyStrategy
    accuracy: float
    artifact_root: str
    committed_hierarchy_path: str
    node_cards_path: str
    verification_report_path: str
    headings_path: str
    raw_hierarchy_path: str
    repair_requests_path: str
    repair_decisions_path: str
    repaired_hierarchy_path: str
    unassigned_spans_path: str
    build_report_path: str
    committed_node_count: int
    unassigned_span_count: int
    toc_detection_path: str | None = None
    toc_reconciliation_path: str | None = None
    llm_verification_assists_path: str | None = None
    node_summaries_path: str | None = None


def _available_strategy_order(
    *,
    current_trust_mode: OutlineTrustMode,
    selected_outline_source: OutlineSource,
    toc_candidates: Sequence[HeadingCandidate],
    gateway_available: bool,
) -> tuple[HierarchyStrategy, ...]:
    outline_available = selected_outline_source != OutlineSource.NONE
    toc_available = bool(toc_candidates)
    weak_outline = (
        not outline_available
    ) or current_trust_mode == OutlineTrustMode.INFERRED_PRIMARY

    strategies: list[HierarchyStrategy] = []
    if outline_available and toc_available:
        strategies.append(HierarchyStrategy.OUTLINE_WITH_TOC_RECONCILIATION)
    if current_trust_mode != OutlineTrustMode.INFERRED_PRIMARY:
        strategies.append(HierarchyStrategy.OUTLINE_ONLY)
    if weak_outline and toc_available:
        strategies.append(HierarchyStrategy.TOC_DERIVED)
    if gateway_available:
        strategies.append(HierarchyStrategy.INFERRED_WITH_LLM_ASSIST)
    strategies.append(HierarchyStrategy.INFERRED_DETERMINISTIC)

    deduplicated: list[HierarchyStrategy] = []
    for strategy in strategies:
        if strategy not in deduplicated:
            deduplicated.append(strategy)
    return tuple(deduplicated)


def select_hierarchy_strategy(
    *,
    current_trust_mode: OutlineTrustMode,
    selected_outline_source: OutlineSource,
    toc_candidates: Sequence[HeadingCandidate],
    gateway_available: bool,
) -> tuple[HierarchyStrategy, StrategyRationale]:
    """Choose the first deterministic strategy and record why it was chosen."""

    ordered = _available_strategy_order(
        current_trust_mode=current_trust_mode,
        selected_outline_source=selected_outline_source,
        toc_candidates=toc_candidates,
        gateway_available=gateway_available,
    )
    outline_available = selected_outline_source != OutlineSource.NONE
    rationale = StrategyRationale(
        reasons=(
            f"default_trust_mode:{current_trust_mode.value}",
            f"initial_strategy:{ordered[0].value}",
        ),
        outline_available=outline_available,
        toc_available=bool(toc_candidates),
        gateway_available=gateway_available,
    )
    return ordered[0], rationale


def execute_hierarchy_strategy(
    *,
    current_trust_mode: OutlineTrustMode,
    selected_outline_source: OutlineSource,
    toc_candidates: Sequence[HeadingCandidate],
    gateway_available: bool,
    settings: TreeSettings,
    attempt_runner: Callable[[HierarchyStrategy, int], StrategyAttemptResult],
) -> tuple[StrategyAttemptResult, StrategyExecutionReport]:
    """Run bounded deterministic strategy attempts until accuracy is sufficient."""

    first_strategy, rationale = select_hierarchy_strategy(
        current_trust_mode=current_trust_mode,
        selected_outline_source=selected_outline_source,
        toc_candidates=toc_candidates,
        gateway_available=gateway_available,
    )
    ordered = _available_strategy_order(
        current_trust_mode=current_trust_mode,
        selected_outline_source=selected_outline_source,
        toc_candidates=toc_candidates,
        gateway_available=gateway_available,
    )

    attempted: list[HierarchyStrategy] = []
    accuracies: list[float] = []
    selected_result: StrategyAttemptResult | None = None
    max_attempts = min(len(ordered), 1 + settings.max_strategy_cascade_depth)

    for attempt_index, strategy in enumerate(ordered[:max_attempts], start=1):
        result = attempt_runner(strategy, attempt_index)
        attempted.append(strategy)
        accuracies.append(result.accuracy)
        selected_result = result
        if result.accuracy >= settings.strategy_accuracy_threshold:
            break

    if selected_result is None:
        msg = "strategy execution produced no attempt results"
        raise RuntimeError(msg)

    report = StrategyExecutionReport(
        attempted_strategies=tuple(attempted),
        selected_strategy=selected_result.strategy,
        rationale=rationale.model_copy(
            update={
                "reasons": (
                    *rationale.reasons,
                    f"first_candidate_strategy:{first_strategy.value}",
                    f"selected_strategy:{selected_result.strategy.value}",
                )
            }
        ),
        cascade_depth=max(0, len(attempted) - 1),
        accuracy_at_each_level=tuple(accuracies),
    )
    return selected_result, report
