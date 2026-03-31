"""Shared runtime helpers for tree-guided retrieval variants."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from nullvector._hierarchy import document_order_key as hierarchy_document_order_key
from nullvector._text import normalize_text, tokenize
from nullvector.domain.common import PageSpan
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalCorpus,
    RetrievalEvidence,
    RetrievalHit,
    RetrievalManifest,
    RetrievalUnitType,
    TreeSearchCandidate,
    TreeSearchFrontierNode,
    TreeSearchMode,
    TreeSearchRequest,
    TreeSearchTerminationSignal,
)
from nullvector.domain.tree import HierarchyNode, NodeCard, NodeSummary, TreeBuildManifest
from nullvector.retrieval._artifacts import (
    load_committed_nodes,
    load_node_cards,
    load_node_summaries,
    load_tree_manifest,
    normalize_artifact_ref,
)
from nullvector.retrieval.load import load_retrieval_corpus, load_retrieval_manifest
from nullvector.retrieval.planner import QueryPlanner
from nullvector.retrieval.service import RetrievalService
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage.artifact_roots import resolve_tree_search_artifact_root
from nullvector.storage.protocol import DocumentStore

_TITLE_WEIGHT = 2.0
_SUMMARY_WEIGHT = 1.5
_KEYWORD_WEIGHT = 1.0
_TITLE_EXACT_BONUS = 3.0
_TITLE_CONTAINS_BONUS = 1.5
_PAGE_EXACT_BONUS = 1.0
_PAGE_OVERLAP_BONUS = 0.5
_MAX_SELECTED_PER_STEP = 2
_MIN_FRONTIER_SCORE = 0.2
_MIN_EVIDENCE_SUFFICIENT_SCORE = 0.5
_DIRECT_RETRIEVAL_TYPES = frozenset(
    {
        RetrievalUnitType.NODE_TEXT,
        RetrievalUnitType.NODE_SUMMARY,
    }
)
_CONTEXTUAL_RETRIEVAL_TYPES = frozenset(
    {
        RetrievalUnitType.PAGE_TEXT,
        RetrievalUnitType.TABLE,
        RetrievalUnitType.VISUAL,
        RetrievalUnitType.UNRESOLVED_VISUAL,
        RetrievalUnitType.UNASSIGNED_SPAN,
    }
)
_TERMINATION_PRIORITY = {
    TreeSearchTerminationSignal.FALLBACK_TO_FLAT_RETRIEVAL: 5,
    TreeSearchTerminationSignal.MAX_DEPTH: 4,
    TreeSearchTerminationSignal.EVIDENCE_SUFFICIENT: 3,
    TreeSearchTerminationSignal.LEAF: 2,
    TreeSearchTerminationSignal.NO_POSITIVE_FRONTIER: 1,
}


@dataclass(frozen=True)
class TreeSearchState:
    """Loaded tree-search state reused across tree-search variants."""

    tree_manifest: TreeBuildManifest
    retrieval_manifest: RetrievalManifest
    corpus: RetrievalCorpus
    nodes_by_id: dict[str, HierarchyNode]
    node_cards_by_id: dict[str, NodeCard]
    node_summaries_by_id: dict[str, NodeSummary]
    children_by_parent: dict[str | None, tuple[str, ...]]
    initial_frontier_node_ids: tuple[str, ...]
    direct_units_by_node: dict[str, tuple[RetrievalEvidence, ...]]
    plan: QueryPlan
    query_tokens: tuple[str, ...]


@dataclass(frozen=True)
class FrontierSelectionDecision:
    """One frontier-selection decision used by the shared runtime."""

    selected_node_ids: tuple[str, ...]
    selection_reason: str
    termination_signal: TreeSearchTerminationSignal | None = None
    applied_preference_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TreeSearchRuntimeTraceStep:
    """Internal auditable tree-search trace step."""

    step_index: int
    frontier_node_ids: tuple[str, ...]
    selected_node_ids: tuple[str, ...]
    selection_reason: str
    termination_signal: TreeSearchTerminationSignal | None = None
    applied_preference_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TreeSearchExecutionResult:
    """Shared tree-search execution result before service-specific persistence."""

    trace_steps: tuple[TreeSearchRuntimeTraceStep, ...]
    selected_nodes: tuple[TreeSearchCandidate, ...]
    retrieval_hits: tuple[RetrievalHit, ...]
    search_mode: TreeSearchMode


def artifact_path(artifact_root: str, filename: str) -> str:
    return str(Path(artifact_root) / filename)


def tree_search_artifact_root(
    *,
    request: TreeSearchRequest,
    tree_run_id: str,
    store: DocumentStore,
) -> str:
    return resolve_tree_search_artifact_root(
        store,
        tree_run_id=tree_run_id,
        search_run_id=request.search_run_id,
        configured_root=request.artifact_root,
    )


def page_span_intersects(left: PageSpan, right: PageSpan) -> bool:
    return not (left.end_page < right.start_page or right.end_page < left.start_page)


def document_order_key(
    node_id: str,
    *,
    node: HierarchyNode,
    node_card: NodeCard | None,
) -> tuple[int, int, int, tuple[str, ...], str]:
    page_span = node_card.page_span if node_card is not None else node.page_span
    path = node_card.path if node_card is not None else node.path
    level = node_card.level if node_card is not None else node.level
    return hierarchy_document_order_key(
        page_span=page_span,
        level=level,
        path=path,
        identifier=node_id,
    )


def frontier_sort_key(
    frontier_node: TreeSearchFrontierNode,
) -> tuple[int, int, int, tuple[str, ...], str]:
    return (
        frontier_node.page_span.start_page,
        frontier_node.page_span.end_page,
        frontier_node.level,
        frontier_node.path,
        frontier_node.node_id,
    )


def summary_text(
    node_id: str,
    *,
    node_cards_by_id: dict[str, NodeCard],
    node_summaries_by_id: dict[str, NodeSummary],
) -> str | None:
    summary = node_summaries_by_id.get(node_id)
    if summary is not None:
        return summary.summary
    node_card = node_cards_by_id.get(node_id)
    return node_card.summary if node_card is not None else None


def keywords(
    node_id: str,
    *,
    node_cards_by_id: dict[str, NodeCard],
    node_summaries_by_id: dict[str, NodeSummary],
) -> tuple[str, ...]:
    node_summary = node_summaries_by_id.get(node_id)
    if node_summary is not None and node_summary.keywords:
        return tuple(node_summary.keywords)
    node_card = node_cards_by_id.get(node_id)
    return tuple(node_card.keywords) if node_card is not None else ()


def build_frontier_node(
    node_id: str,
    *,
    nodes_by_id: dict[str, HierarchyNode],
    node_cards_by_id: dict[str, NodeCard],
    node_summaries_by_id: dict[str, NodeSummary],
) -> TreeSearchFrontierNode:
    node = nodes_by_id[node_id]
    node_card = node_cards_by_id.get(node_id)
    return TreeSearchFrontierNode(
        node_id=node_id,
        title=node_card.title if node_card is not None else node.title,
        path=node_card.path if node_card is not None else node.path,
        level=node_card.level if node_card is not None else node.level,
        page_span=node_card.page_span if node_card is not None else node.page_span,
        summary_text=summary_text(
            node_id,
            node_cards_by_id=node_cards_by_id,
            node_summaries_by_id=node_summaries_by_id,
        ),
        keywords=keywords(
            node_id,
            node_cards_by_id=node_cards_by_id,
            node_summaries_by_id=node_summaries_by_id,
        ),
    )


def token_overlap_score(text: str | None, query_tokens: tuple[str, ...]) -> float:
    if not text or not query_tokens:
        return 0.0
    text_tokens = frozenset(tokenize(text))
    if not text_tokens:
        return 0.0
    matched = tuple(token for token in query_tokens if token in text_tokens)
    return float(len(matched)) / float(len(query_tokens))


def frontier_score(
    frontier_node: TreeSearchFrontierNode,
    *,
    plan: QueryPlan,
    query_tokens: tuple[str, ...],
) -> float:
    score = 0.0
    score += token_overlap_score(frontier_node.title, query_tokens) * _TITLE_WEIGHT
    score += token_overlap_score(frontier_node.summary_text, query_tokens) * _SUMMARY_WEIGHT
    score += token_overlap_score(" ".join(frontier_node.keywords), query_tokens) * _KEYWORD_WEIGHT

    normalized_title = normalize_text(frontier_node.title)
    for phrase in plan.title_like_phrases:
        normalized_phrase = normalize_text(phrase)
        if normalized_phrase and normalized_phrase == normalized_title:
            score += _TITLE_EXACT_BONUS
        elif normalized_phrase and normalized_phrase in normalized_title:
            score += _TITLE_CONTAINS_BONUS

    if plan.page_filter is not None:
        if frontier_node.page_span == plan.page_filter:
            score += _PAGE_EXACT_BONUS
        elif page_span_intersects(frontier_node.page_span, plan.page_filter):
            score += _PAGE_OVERLAP_BONUS

    return score


def direct_retrieval_units_by_node(
    corpus: RetrievalCorpus,
) -> dict[str, tuple[RetrievalEvidence, ...]]:
    grouped: dict[str, list[RetrievalEvidence]] = {}
    for unit in corpus.units:
        if unit.node_id is None or unit.unit_type not in _DIRECT_RETRIEVAL_TYPES:
            continue
        grouped.setdefault(unit.node_id, []).append(unit)
    return {node_id: tuple(units) for node_id, units in grouped.items()}


def contextual_retrieval_units(
    corpus: RetrievalCorpus,
    *,
    selected_page_spans: tuple[PageSpan, ...],
) -> tuple[RetrievalEvidence, ...]:
    contextual: list[RetrievalEvidence] = []
    for unit in corpus.units:
        if unit.unit_type not in _CONTEXTUAL_RETRIEVAL_TYPES:
            continue
        if any(page_span_intersects(unit.page_span, span) for span in selected_page_spans):
            contextual.append(unit)
    return tuple(contextual)


def dedupe_units(units: tuple[RetrievalEvidence, ...]) -> tuple[RetrievalEvidence, ...]:
    deduped: list[RetrievalEvidence] = []
    seen: set[str] = set()
    for unit in units:
        if unit.unit_id in seen:
            continue
        seen.add(unit.unit_id)
        deduped.append(unit)
    return tuple(deduped)


def evidence_overlap_score(
    units: tuple[RetrievalEvidence, ...],
    *,
    plan: QueryPlan,
    query_tokens: tuple[str, ...],
) -> float:
    best_score = 0.0
    for unit in units:
        score = token_overlap_score(
            " ".join(part for part in (unit.title or "", unit.text or "") if part),
            query_tokens,
        )
        for phrase in plan.title_like_phrases:
            normalized_phrase = normalize_text(phrase)
            normalized_title = normalize_text(unit.title or "")
            if normalized_phrase and normalized_phrase == normalized_title:
                score += _TITLE_EXACT_BONUS
            elif normalized_phrase and normalized_phrase in normalized_title:
                score += _TITLE_CONTAINS_BONUS
        if score > best_score:
            best_score = score
    return best_score


def aggregate_termination_signal(
    signals: tuple[TreeSearchTerminationSignal, ...],
) -> TreeSearchTerminationSignal | None:
    if not signals:
        return None
    return max(signals, key=lambda signal: _TERMINATION_PRIORITY[signal])


def trace_reason_for_selection(
    selected_scores: tuple[tuple[str, float], ...],
) -> str:
    if not selected_scores:
        return "No frontier nodes produced a positive tree-search score."
    parts = ", ".join(f"{node_id}={score:.2f}" for node_id, score in selected_scores)
    return f"Selected frontier nodes by tree-search score: {parts}"


def build_adjacency_maps(
    committed_nodes: tuple[HierarchyNode, ...],
    *,
    node_cards_by_id: dict[str, NodeCard],
) -> tuple[dict[str | None, tuple[str, ...]], tuple[str, ...]]:
    nodes_by_id = {node.node_id: node for node in committed_nodes}
    ordered_node_ids = tuple(
        sorted(
            nodes_by_id,
            key=lambda node_id: document_order_key(
                node_id,
                node=nodes_by_id[node_id],
                node_card=node_cards_by_id.get(node_id),
            ),
        )
    )
    children_by_parent: dict[str | None, list[str]] = {}
    for node_id in ordered_node_ids:
        parent_id = nodes_by_id[node_id].parent_id
        children_by_parent.setdefault(parent_id, []).append(node_id)
    return (
        {parent_id: tuple(children) for parent_id, children in children_by_parent.items()},
        ordered_node_ids,
    )


def seed_frontier(
    *,
    committed_nodes: tuple[HierarchyNode, ...],
    node_cards_by_id: dict[str, NodeCard],
) -> tuple[str, ...]:
    children_by_parent, ordered_node_ids = build_adjacency_maps(
        committed_nodes,
        node_cards_by_id=node_cards_by_id,
    )
    explicit_roots = children_by_parent.get(None, ())
    if explicit_roots:
        return explicit_roots
    if not committed_nodes:
        return ()
    nodes_by_id = {node.node_id: node for node in committed_nodes}
    min_level = min(node.level for node in committed_nodes)
    return tuple(node_id for node_id in ordered_node_ids if nodes_by_id[node_id].level == min_level)


def deterministic_selection(
    frontier_nodes: tuple[TreeSearchFrontierNode, ...],
    *,
    plan: QueryPlan,
    query_tokens: tuple[str, ...],
    score_fn: Callable[[TreeSearchFrontierNode], float] | None = None,
) -> FrontierSelectionDecision:
    scorer = score_fn or (lambda node: frontier_score(node, plan=plan, query_tokens=query_tokens))
    scored = tuple(
        sorted(
            ((node.node_id, scorer(node), node) for node in frontier_nodes),
            key=lambda item: (-item[1], frontier_sort_key(item[2])),
        )
    )
    if scored and scored[0][1] <= 0.0 and len(frontier_nodes) == 1:
        node_id, score, _node = scored[0]
        return FrontierSelectionDecision(
            selected_node_ids=(node_id,),
            selection_reason=(
                "Advanced through the single available frontier node despite low lexical "
                f"score: {node_id}={score:.2f}"
            ),
        )

    selected_scores: tuple[tuple[str, float], ...] = ()
    if scored and scored[0][1] > 0.0:
        best_score = scored[0][1]
        minimum_selected_score = max(_MIN_FRONTIER_SCORE, best_score * 0.5)
        selected_scores = tuple(
            (node_id, score) for node_id, score, _node in scored if score >= minimum_selected_score
        )[:_MAX_SELECTED_PER_STEP]
    selected_node_ids = tuple(node_id for node_id, _score in selected_scores)
    return FrontierSelectionDecision(
        selected_node_ids=selected_node_ids,
        selection_reason=trace_reason_for_selection(selected_scores),
    )


def selected_frontier_scores(
    frontier_nodes: tuple[TreeSearchFrontierNode, ...],
    *,
    selected_node_ids: tuple[str, ...],
    plan: QueryPlan,
    query_tokens: tuple[str, ...],
    score_fn: Callable[[TreeSearchFrontierNode], float] | None = None,
) -> tuple[tuple[str, float], ...]:
    scorer = score_fn or (lambda node: frontier_score(node, plan=plan, query_tokens=query_tokens))
    nodes_by_id = {node.node_id: node for node in frontier_nodes}
    return tuple(
        (
            node_id,
            scorer(nodes_by_id[node_id]),
        )
        for node_id in selected_node_ids
        if node_id in nodes_by_id
    )


def dedupe_node_ids(node_ids: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for node_id in node_ids:
        if node_id in seen:
            continue
        seen.add(node_id)
        ordered.append(node_id)
    return tuple(ordered)


def _unit_matches_phrase(
    units: tuple[RetrievalEvidence, ...],
    phrase: str,
) -> bool:
    normalized_phrase = normalize_text(phrase)
    if not normalized_phrase:
        return False
    for unit in units:
        haystack = normalize_text(
            " ".join(part for part in (unit.title or "", unit.text or "") if part)
        )
        if normalized_phrase and normalized_phrase in haystack:
            return True
    return False


def evidence_is_sufficient(
    units: tuple[RetrievalEvidence, ...],
    *,
    plan: QueryPlan,
    query_tokens: tuple[str, ...],
) -> bool:
    if not units:
        return False
    if plan.page_filter is not None:
        return True
    if any(_unit_matches_phrase(units, phrase) for phrase in plan.quoted_phrases):
        return True
    return (
        evidence_overlap_score(
            units,
            plan=plan,
            query_tokens=query_tokens,
        )
        >= _MIN_EVIDENCE_SUFFICIENT_SCORE
    )


def load_tree_search_state(
    *,
    request: TreeSearchRequest,
    planner: QueryPlanner,
    storage: StorageConfig | None,
) -> TreeSearchState:
    input_store = build_document_store(storage, default_filesystem_root=".")
    tree_manifest_ref = cast(str, normalize_artifact_ref(request.tree_manifest_path))
    retrieval_manifest_ref = cast(str, normalize_artifact_ref(request.retrieval_manifest_path))
    tree_manifest = load_tree_manifest(input_store, tree_manifest_ref)
    if tree_manifest is None:
        msg = "tree search requires a valid tree manifest"
        raise ValueError(msg)
    retrieval_manifest = load_retrieval_manifest(
        retrieval_manifest_ref,
        storage=storage,
    )
    corpus = load_retrieval_corpus(retrieval_manifest.corpus_path, storage=storage)
    if tree_manifest.document_id != retrieval_manifest.document_id:
        msg = "tree manifest and retrieval manifest must reference the same document_id"
        raise ValueError(msg)
    if corpus.document_id != tree_manifest.document_id:
        msg = "tree manifest and retrieval corpus must reference the same document_id"
        raise ValueError(msg)

    committed_nodes = load_committed_nodes(input_store, tree_manifest)
    node_cards = load_node_cards(input_store, tree_manifest)
    node_summaries = load_node_summaries(input_store, tree_manifest)
    if not committed_nodes:
        msg = "tree search requires committed hierarchy nodes"
        raise ValueError(msg)
    if not node_cards:
        msg = "tree search requires persisted node cards"
        raise ValueError(msg)

    nodes_by_id = {node.node_id: node for node in committed_nodes}
    node_cards_by_id = {node_card.node_id: node_card for node_card in node_cards}
    node_summaries_by_id = {node_summary.node_id: node_summary for node_summary in node_summaries}
    children_by_parent, _ordered_node_ids = build_adjacency_maps(
        committed_nodes,
        node_cards_by_id=node_cards_by_id,
    )
    initial_frontier_node_ids = seed_frontier(
        committed_nodes=committed_nodes,
        node_cards_by_id=node_cards_by_id,
    )
    if not initial_frontier_node_ids:
        msg = "tree search requires at least one frontier node"
        raise ValueError(msg)

    return TreeSearchState(
        tree_manifest=tree_manifest,
        retrieval_manifest=retrieval_manifest,
        corpus=corpus,
        nodes_by_id=nodes_by_id,
        node_cards_by_id=node_cards_by_id,
        node_summaries_by_id=node_summaries_by_id,
        children_by_parent=children_by_parent,
        initial_frontier_node_ids=initial_frontier_node_ids,
        direct_units_by_node=direct_retrieval_units_by_node(corpus),
        plan=planner.plan(request.query),
        query_tokens=tokenize(request.query),
    )


def execute_tree_search(
    *,
    state: TreeSearchState,
    request: TreeSearchRequest,
    retrieval_service: RetrievalService,
    search_mode: TreeSearchMode,
    frontier_selector: Callable[
        [tuple[TreeSearchFrontierNode, ...], int],
        FrontierSelectionDecision,
    ],
    frontier_score_fn: Callable[[TreeSearchFrontierNode], float] | None = None,
) -> TreeSearchExecutionResult:
    frontier_node_ids = state.initial_frontier_node_ids
    trace_steps: list[TreeSearchRuntimeTraceStep] = []
    selected_candidates: dict[str, TreeSearchCandidate] = {}
    fallback_to_flat = False

    for step_index in range(request.max_depth):
        frontier_nodes = tuple(
            sorted(
                (
                    build_frontier_node(
                        node_id,
                        nodes_by_id=state.nodes_by_id,
                        node_cards_by_id=state.node_cards_by_id,
                        node_summaries_by_id=state.node_summaries_by_id,
                    )
                    for node_id in frontier_node_ids
                ),
                key=frontier_sort_key,
            )[: request.max_frontier_size]
        )
        current_depth = step_index + 1
        decision = frontier_selector(frontier_nodes, current_depth)
        if decision.termination_signal is TreeSearchTerminationSignal.FALLBACK_TO_FLAT_RETRIEVAL:
            trace_steps.append(
                TreeSearchRuntimeTraceStep(
                    step_index=step_index,
                    frontier_node_ids=tuple(node.node_id for node in frontier_nodes),
                    selected_node_ids=decision.selected_node_ids,
                    selection_reason=decision.selection_reason,
                    termination_signal=TreeSearchTerminationSignal.FALLBACK_TO_FLAT_RETRIEVAL,
                    applied_preference_ids=decision.applied_preference_ids,
                )
            )
            fallback_to_flat = True
            break

        if not decision.selected_node_ids:
            termination_signal = (
                TreeSearchTerminationSignal.FALLBACK_TO_FLAT_RETRIEVAL
                if step_index == 0 and not selected_candidates
                else TreeSearchTerminationSignal.NO_POSITIVE_FRONTIER
            )
            trace_steps.append(
                TreeSearchRuntimeTraceStep(
                    step_index=step_index,
                    frontier_node_ids=tuple(node.node_id for node in frontier_nodes),
                    selected_node_ids=(),
                    selection_reason=decision.selection_reason,
                    termination_signal=termination_signal,
                    applied_preference_ids=decision.applied_preference_ids,
                )
            )
            fallback_to_flat = (
                termination_signal is TreeSearchTerminationSignal.FALLBACK_TO_FLAT_RETRIEVAL
            )
            break

        selected_scores = selected_frontier_scores(
            frontier_nodes,
            selected_node_ids=decision.selected_node_ids,
            plan=state.plan,
            query_tokens=state.query_tokens,
            score_fn=frontier_score_fn,
        )
        next_frontier_ids: list[str] = []
        processed_selected_ids: list[str] = []
        terminal_signals: list[TreeSearchTerminationSignal] = []

        for node_id, score in selected_scores:
            processed_selected_ids.append(node_id)
            direct_units = state.direct_units_by_node.get(node_id, ())
            child_node_ids = state.children_by_parent.get(node_id, ())
            if decision.termination_signal is not None:
                terminal_signal = decision.termination_signal
            elif not child_node_ids:
                terminal_signal = TreeSearchTerminationSignal.LEAF
            elif current_depth >= request.max_depth:
                terminal_signal = TreeSearchTerminationSignal.MAX_DEPTH
            elif evidence_is_sufficient(
                direct_units,
                plan=state.plan,
                query_tokens=state.query_tokens,
            ):
                terminal_signal = TreeSearchTerminationSignal.EVIDENCE_SUFFICIENT
            else:
                terminal_signal = None

            if terminal_signal is None:
                next_frontier_ids.extend(child_node_ids)
                continue

            terminal_signals.append(terminal_signal)
            if (
                node_id not in selected_candidates
                and len(selected_candidates) < request.max_selected_nodes
            ):
                node = state.nodes_by_id[node_id]
                node_card = state.node_cards_by_id.get(node_id)
                page_span = node_card.page_span if node_card is not None else node.page_span
                selected_candidates[node_id] = TreeSearchCandidate(
                    node_id=node_id,
                    page_span=page_span,
                    retrieval_evidence_ids=tuple(unit.unit_id for unit in direct_units),
                    score=score,
                )

        next_frontier_ids = list(dedupe_node_ids(tuple(next_frontier_ids)))
        step_termination_signal: TreeSearchTerminationSignal | None = None
        if len(selected_candidates) >= request.max_selected_nodes or not next_frontier_ids:
            step_termination_signal = aggregate_termination_signal(tuple(terminal_signals))
        elif decision.termination_signal is not None:
            step_termination_signal = decision.termination_signal

        trace_steps.append(
            TreeSearchRuntimeTraceStep(
                step_index=step_index,
                frontier_node_ids=tuple(node.node_id for node in frontier_nodes),
                selected_node_ids=tuple(processed_selected_ids),
                selection_reason=decision.selection_reason,
                termination_signal=step_termination_signal,
                applied_preference_ids=decision.applied_preference_ids,
            )
        )
        if step_termination_signal is not None:
            break
        frontier_node_ids = tuple(next_frontier_ids)

    selected_nodes = tuple(
        sorted(
            selected_candidates.values(),
            key=lambda candidate: (
                -candidate.score,
                candidate.page_span.start_page,
                candidate.page_span.end_page,
                candidate.node_id,
            ),
        )
    )
    if fallback_to_flat or not selected_nodes:
        retrieval_hits = retrieval_service.search(
            corpus=state.corpus,
            query=request.query,
            limit=request.retrieval_limit,
        )
    else:
        selected_page_spans = tuple(candidate.page_span for candidate in selected_nodes)
        direct_units = tuple(
            unit
            for candidate in selected_nodes
            for unit in state.direct_units_by_node.get(candidate.node_id, ())
        )
        narrowed_units = dedupe_units(
            direct_units
            + contextual_retrieval_units(
                state.corpus,
                selected_page_spans=selected_page_spans,
            )
        )
        narrowed_corpus = RetrievalCorpus(
            document_id=state.corpus.document_id,
            units=narrowed_units,
        )
        retrieval_hits = retrieval_service.search(
            corpus=narrowed_corpus,
            query=request.query,
            limit=request.retrieval_limit,
        )

    return TreeSearchExecutionResult(
        trace_steps=tuple(trace_steps),
        selected_nodes=selected_nodes,
        retrieval_hits=tuple(retrieval_hits),
        search_mode=search_mode,
    )


__all__ = [
    "FrontierSelectionDecision",
    "TreeSearchExecutionResult",
    "TreeSearchRuntimeTraceStep",
    "TreeSearchState",
    "aggregate_termination_signal",
    "artifact_path",
    "build_adjacency_maps",
    "build_frontier_node",
    "contextual_retrieval_units",
    "dedupe_node_ids",
    "dedupe_units",
    "deterministic_selection",
    "direct_retrieval_units_by_node",
    "document_order_key",
    "evidence_overlap_score",
    "execute_tree_search",
    "frontier_score",
    "frontier_sort_key",
    "keywords",
    "load_tree_search_state",
    "page_span_intersects",
    "seed_frontier",
    "selected_frontier_scores",
    "summary_text",
    "token_overlap_score",
    "trace_reason_for_selection",
    "tree_search_artifact_root",
]
