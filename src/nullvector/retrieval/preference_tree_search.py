"""Preference-aware overlay for tree-guided retrieval."""

from __future__ import annotations

from logging import Logger
from typing import Protocol

from nullvector._text import normalize_text, tokenize
from nullvector.domain.retrieval import (
    PreferenceAwareTreeSearchRequest,
    PreferenceAwareTreeSearchResponse,
    PreferenceAwareTreeSearchTraceStep,
    PreferenceScope,
    PreferenceSelectionRequest,
    PreferenceSelectionResult,
    PreferenceSnippet,
    RetrievalHit,
    TreeSearchCandidate,
    TreeSearchFrontierNode,
    TreeSearchMode,
    TreeSearchRequest,
)
from nullvector.llm.prompts.preference_tree_search import (
    PreferenceTreeSearchFrontierPromptResponse,
    build_preference_tree_search_frontier_messages,
)
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.retrieval._tree_search_runtime import (
    FrontierSelectionDecision,
    artifact_path,
    deterministic_selection,
    execute_tree_search,
    frontier_score,
    load_tree_search_state,
    selected_frontier_scores,
    token_overlap_score,
    trace_reason_for_selection,
    tree_search_artifact_root,
)
from nullvector.retrieval.planner import QueryPlanner
from nullvector.retrieval.service import RetrievalService
from nullvector.retrieval.tree_search import TreeSearchService
from nullvector.storage import StorageConfig, build_document_store

_SCOPE_ORDER = {
    PreferenceScope.USER: 0,
    PreferenceScope.TENANT: 1,
    PreferenceScope.DOMAIN_RULE: 2,
    PreferenceScope.GLOBAL: 3,
}
_PREFERENCE_EXACT_BONUS = 0.5
_PREFERENCE_NODE_EXACT_BONUS = 0.25
_MAX_PREFERENCE_BONUS = 0.75


class PreferenceRepository(Protocol):
    """External source for retrieval-time preference snippets."""

    def load_snippets(self) -> tuple[PreferenceSnippet, ...]:
        """Return the candidate preference snippets for the current environment."""


def _base_tree_search_request(request: PreferenceAwareTreeSearchRequest) -> TreeSearchRequest:
    payload = request.model_dump(
        mode="python",
        exclude={"preference_snippets", "max_preference_snippets"},
    )
    return TreeSearchRequest(**payload)


def _snippet_selection_score(snippet: PreferenceSnippet, *, query: str) -> float:
    query_tokens = tuple(tokenize(query))
    score = token_overlap_score(snippet.text, query_tokens)
    normalized_query = normalize_text(query)
    normalized_text = normalize_text(snippet.text)
    if normalized_query and normalized_query in normalized_text:
        score += _PREFERENCE_EXACT_BONUS
    return score


def _combined_frontier_text(frontier_node: TreeSearchFrontierNode) -> str:
    return " ".join(
        part
        for part in (
            frontier_node.title,
            frontier_node.summary_text or "",
            " ".join(frontier_node.keywords),
        )
        if part
    )


def _preference_match_score(
    frontier_node: TreeSearchFrontierNode,
    snippet: PreferenceSnippet,
) -> float:
    combined_text = _combined_frontier_text(frontier_node)
    snippet_tokens = tuple(tokenize(snippet.text))
    score = token_overlap_score(combined_text, snippet_tokens)
    normalized_combined = normalize_text(combined_text)
    normalized_snippet = normalize_text(snippet.text)
    if normalized_snippet and normalized_snippet in normalized_combined:
        score += _PREFERENCE_NODE_EXACT_BONUS
    return min(score, _MAX_PREFERENCE_BONUS)


def _applied_preference_ids(
    *,
    frontier_nodes: tuple[TreeSearchFrontierNode, ...],
    selected_node_ids: tuple[str, ...],
    selected_snippets: tuple[PreferenceSnippet, ...],
) -> tuple[str, ...]:
    if not selected_node_ids:
        return ()
    nodes_by_id = {node.node_id: node for node in frontier_nodes}
    applied: list[str] = []
    for snippet in selected_snippets:
        if any(
            node_id in nodes_by_id and _preference_match_score(nodes_by_id[node_id], snippet) > 0.0
            for node_id in selected_node_ids
        ):
            applied.append(snippet.preference_id)
    return tuple(applied)


class PreferenceSelectionService:
    """Deterministically select a bounded set of relevant preference snippets."""

    def select(self, request: PreferenceSelectionRequest) -> PreferenceSelectionResult:
        scored = tuple(
            (
                snippet,
                _snippet_selection_score(snippet, query=request.query),
            )
            for snippet in request.snippets
        )
        positive = tuple(item for item in scored if item[1] > 0.0)
        ordered = tuple(
            sorted(
                positive,
                key=lambda item: (
                    -item[1],
                    -item[0].priority,
                    _SCOPE_ORDER[item[0].scope],
                    item[0].preference_id,
                ),
            )
        )
        selected = tuple(snippet for snippet, _score in ordered[: request.limit])
        if not request.snippets:
            reason = "No preference snippets were provided."
        elif not selected:
            reason = "No preference snippets matched the query strongly enough."
        else:
            selected_ids = ", ".join(snippet.preference_id for snippet in selected)
            reason = f"Selected preference snippets by overlap and priority: {selected_ids}"
        return PreferenceSelectionResult(
            selected_snippets=selected,
            selection_reason=reason,
        )


class PreferenceAwareTreeSearchService:
    """Preference-aware tree search that preserves the base narrowed retrieval flow."""

    def __init__(
        self,
        planner: QueryPlanner,
        retrieval_service: RetrievalService,
        *,
        preference_repository: PreferenceRepository | None = None,
        preference_selection_service: PreferenceSelectionService | None = None,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._planner = planner
        self._retrieval_service = retrieval_service
        self._preference_repository = preference_repository
        self._preference_selection_service = (
            preference_selection_service or PreferenceSelectionService()
        )
        self._logger = resolve_runtime_logger(logger)
        self._storage = storage
        self._tree_search_service = TreeSearchService(
            planner,
            retrieval_service,
            logger=self._logger,
            storage=storage,
        )

    def search(
        self,
        request: PreferenceAwareTreeSearchRequest,
        *,
        gateway: StructuredLLMGateway | None = None,
    ) -> PreferenceAwareTreeSearchResponse:
        candidate_snippets = (
            request.preference_snippets
            if request.preference_snippets
            else (
                self._preference_repository.load_snippets()
                if self._preference_repository is not None
                else ()
            )
        )
        log_event(
            self._logger,
            "PreferenceSelectionStarted",
            query=request.query,
            search_run_id=request.search_run_id,
            candidate_count=len(candidate_snippets),
            limit=request.max_preference_snippets,
        )
        selection_result = self._preference_selection_service.select(
            PreferenceSelectionRequest(
                query=request.query,
                snippets=candidate_snippets,
                limit=request.max_preference_snippets,
            )
        )
        log_event(
            self._logger,
            "PreferenceSelectionCompleted",
            query=request.query,
            search_run_id=request.search_run_id,
            candidate_count=len(candidate_snippets),
            selected_snippet_count=len(selection_result.selected_snippets),
        )

        base_request = _base_tree_search_request(request)
        if not selection_result.selected_snippets:
            base_response = self._tree_search_service.search(base_request, gateway=gateway)
            return self._persist_wrapped_response(
                request=request,
                selection_result=selection_result,
                search_mode=base_response.search_mode,
                trace_steps=tuple(
                    PreferenceAwareTreeSearchTraceStep(
                        step_index=step.step_index,
                        frontier_node_ids=step.frontier_node_ids,
                        selected_node_ids=step.selected_node_ids,
                        selection_reason=step.selection_reason,
                        termination_signal=step.termination_signal,
                        applied_preference_ids=(),
                    )
                    for step in base_response.trace
                ),
                selected_nodes=base_response.selected_nodes,
                retrieval_hits=base_response.retrieval_hits,
                artifact_root=base_response.artifact_root,
                tree_run_id=base_response.tree_run_id,
                document_id=base_response.document_id,
                fell_back_to_base_tree_search=False,
            )

        state = load_tree_search_state(
            request=base_request,
            planner=self._planner,
            storage=self._storage,
        )
        log_event(
            self._logger,
            "PreferenceAwareTreeSearchStarted",
            document_id=state.tree_manifest.document_id,
            tree_run_id=state.tree_manifest.tree_run_id,
            search_run_id=request.search_run_id,
            query=request.query,
            selected_snippet_count=len(selection_result.selected_snippets),
            max_depth=request.max_depth,
        )
        selected_snippets = selection_result.selected_snippets

        def _preference_score(frontier_node: TreeSearchFrontierNode) -> float:
            base_score = frontier_score(
                frontier_node,
                plan=state.plan,
                query_tokens=state.query_tokens,
            )
            preference_bonus = max(
                (_preference_match_score(frontier_node, snippet) for snippet in selected_snippets),
                default=0.0,
            )
            return base_score + preference_bonus

        def _deterministic_preference_selection(
            frontier_nodes: tuple[TreeSearchFrontierNode, ...],
            _unused_depth: int,
        ) -> FrontierSelectionDecision:
            base_decision = deterministic_selection(
                frontier_nodes,
                plan=state.plan,
                query_tokens=state.query_tokens,
                score_fn=_preference_score,
            )
            applied_ids = _applied_preference_ids(
                frontier_nodes=frontier_nodes,
                selected_node_ids=base_decision.selected_node_ids,
                selected_snippets=selected_snippets,
            )
            selected_scores = selected_frontier_scores(
                frontier_nodes,
                selected_node_ids=base_decision.selected_node_ids,
                plan=state.plan,
                query_tokens=state.query_tokens,
                score_fn=_preference_score,
            )
            reason = trace_reason_for_selection(selected_scores)
            if applied_ids:
                reason = f"{reason} Applied preferences: {', '.join(applied_ids)}."
            return FrontierSelectionDecision(
                selected_node_ids=base_decision.selected_node_ids,
                selection_reason=reason,
                applied_preference_ids=applied_ids,
            )

        gateway_preference_selection = None
        if gateway is not None:
            llm_gateway = gateway

            def _gateway_preference_selection(
                frontier_nodes: tuple[TreeSearchFrontierNode, ...],
                current_depth: int,
            ) -> FrontierSelectionDecision:
                gateway_result = llm_gateway.invoke(
                    GatewayRequest[PreferenceTreeSearchFrontierPromptResponse](
                        operation_name="preference_tree_search_frontier",
                        messages=build_preference_tree_search_frontier_messages(
                            query=request.query,
                            normalized_query=state.plan.normalized_query,
                            frontier_nodes=tuple(
                                node.model_dump(mode="json") for node in frontier_nodes
                            ),
                            preference_snippets=tuple(
                                snippet.model_dump(mode="json") for snippet in selected_snippets
                            ),
                            current_depth=current_depth,
                            max_depth=request.max_depth,
                        ),
                        response_model=PreferenceTreeSearchFrontierPromptResponse,
                        max_output_tokens=300,
                        metadata={
                            "query": request.query,
                            "current_depth": current_depth,
                            "max_depth": request.max_depth,
                            "frontier_count": len(frontier_nodes),
                            "preference_count": len(selected_snippets),
                        },
                    )
                )
                frontier_ids = {node.node_id for node in frontier_nodes}
                invalid_node_ids = tuple(
                    sorted(
                        {
                            node_id
                            for node_id in gateway_result.output.selected_node_ids
                            if node_id not in frontier_ids
                        }
                    )
                )
                if invalid_node_ids:
                    msg = (
                        "preference_tree_search_frontier returned node_ids outside the "
                        f"provided frontier: {invalid_node_ids}"
                    )
                    raise ValueError(msg)
                selected_preference_ids = {snippet.preference_id for snippet in selected_snippets}
                invalid_preference_ids = tuple(
                    sorted(
                        {
                            preference_id
                            for preference_id in gateway_result.output.applied_preference_ids
                            if preference_id not in selected_preference_ids
                        }
                    )
                )
                if invalid_preference_ids:
                    msg = (
                        "preference_tree_search_frontier returned preference_ids outside the "
                        f"selected preference set: {invalid_preference_ids}"
                    )
                    raise ValueError(msg)
                selected_node_ids: list[str] = []
                seen: set[str] = set()
                for node_id in gateway_result.output.selected_node_ids:
                    if node_id in seen:
                        continue
                    seen.add(node_id)
                    selected_node_ids.append(node_id)
                    if len(selected_node_ids) >= 2:
                        break
                return FrontierSelectionDecision(
                    selected_node_ids=tuple(selected_node_ids),
                    selection_reason=gateway_result.output.selection_reason,
                    termination_signal=gateway_result.output.termination_signal,
                    applied_preference_ids=gateway_result.output.applied_preference_ids,
                )

            gateway_preference_selection = _gateway_preference_selection

        execution = execute_tree_search(
            state=state,
            request=base_request,
            retrieval_service=self._retrieval_service,
            search_mode=TreeSearchMode.LLM if gateway is not None else TreeSearchMode.DETERMINISTIC,
            frontier_selector=(
                gateway_preference_selection
                if gateway_preference_selection is not None
                else _deterministic_preference_selection
            ),
            frontier_score_fn=_preference_score,
        )

        fell_back = False
        if not execution.selected_nodes or not execution.retrieval_hits:
            base_execution = execute_tree_search(
                state=state,
                request=base_request,
                retrieval_service=self._retrieval_service,
                search_mode=TreeSearchMode.DETERMINISTIC,
                frontier_selector=lambda frontier_nodes, _unused_depth: deterministic_selection(
                    frontier_nodes,
                    plan=state.plan,
                    query_tokens=state.query_tokens,
                ),
            )
            if base_execution.selected_nodes and base_execution.retrieval_hits:
                execution = base_execution
                fell_back = True

        artifact_root = tree_search_artifact_root(
            request=base_request,
            tree_run_id=state.tree_manifest.tree_run_id,
            storage=self._storage,
        )
        trace_steps = tuple(
            PreferenceAwareTreeSearchTraceStep(
                step_index=step.step_index,
                frontier_node_ids=step.frontier_node_ids,
                selected_node_ids=step.selected_node_ids,
                selection_reason=step.selection_reason,
                termination_signal=step.termination_signal,
                applied_preference_ids=step.applied_preference_ids,
            )
            for step in execution.trace_steps
        )
        for step in trace_steps:
            log_event(
                self._logger,
                "PreferenceAwareTreeSearchStepSelected",
                document_id=state.tree_manifest.document_id,
                tree_run_id=state.tree_manifest.tree_run_id,
                search_run_id=request.search_run_id,
                step_index=step.step_index,
                frontier_node_ids=step.frontier_node_ids,
                selected_node_ids=step.selected_node_ids,
                applied_preference_ids=step.applied_preference_ids,
                termination_signal=(
                    step.termination_signal.value if step.termination_signal is not None else None
                ),
            )
        return self._persist_wrapped_response(
            request=request,
            selection_result=selection_result,
            search_mode=execution.search_mode,
            trace_steps=trace_steps,
            selected_nodes=execution.selected_nodes,
            retrieval_hits=execution.retrieval_hits,
            artifact_root=artifact_root,
            tree_run_id=state.tree_manifest.tree_run_id,
            document_id=state.tree_manifest.document_id,
            fell_back_to_base_tree_search=fell_back,
        )

    def _persist_wrapped_response(
        self,
        *,
        request: PreferenceAwareTreeSearchRequest,
        selection_result: PreferenceSelectionResult,
        search_mode: TreeSearchMode,
        trace_steps: tuple[PreferenceAwareTreeSearchTraceStep, ...],
        selected_nodes: tuple[TreeSearchCandidate, ...],
        retrieval_hits: tuple[RetrievalHit, ...],
        artifact_root: str | None,
        tree_run_id: str,
        document_id: str,
        fell_back_to_base_tree_search: bool,
    ) -> PreferenceAwareTreeSearchResponse:
        if artifact_root is None:
            msg = "preference-aware tree search requires a concrete artifact_root"
            raise RuntimeError(msg)
        store = build_document_store(self._storage, default_filesystem_root=".")
        preference_selection_path = store.put_json_artifact(
            run_type="tree_search",
            run_id=request.search_run_id,
            document_id=document_id,
            artifact_kind="tree_search",
            artifact_path=artifact_path(artifact_root, "preference-selection.json"),
            payload={
                "tree_run_id": tree_run_id,
                "document_id": document_id,
                "query": request.query,
                "selection_reason": selection_result.selection_reason,
                "selected_snippets": tuple(
                    snippet.model_dump(mode="json")
                    for snippet in selection_result.selected_snippets
                ),
            },
        )
        trace_path = store.put_json_artifact(
            run_type="tree_search",
            run_id=request.search_run_id,
            document_id=document_id,
            artifact_kind="tree_search",
            artifact_path=artifact_path(artifact_root, "preference-aware-trace.json"),
            payload={
                "tree_run_id": tree_run_id,
                "document_id": document_id,
                "search_mode": search_mode.value,
                "fell_back_to_base_tree_search": fell_back_to_base_tree_search,
                "trace": tuple(step.model_dump(mode="json") for step in trace_steps),
            },
        )
        results_path = store.put_json_artifact(
            run_type="tree_search",
            run_id=request.search_run_id,
            document_id=document_id,
            artifact_kind="tree_search",
            artifact_path=artifact_path(artifact_root, "preference-aware-results.json"),
            payload={
                "tree_run_id": tree_run_id,
                "document_id": document_id,
                "search_mode": search_mode.value,
                "query": request.query,
                "fell_back_to_base_tree_search": fell_back_to_base_tree_search,
                "selected_nodes": tuple(
                    candidate.model_dump(mode="json") for candidate in selected_nodes
                ),
                "retrieval_hits": tuple(hit.model_dump(mode="json") for hit in retrieval_hits),
            },
        )
        response = PreferenceAwareTreeSearchResponse(
            tree_run_id=tree_run_id,
            document_id=document_id,
            preference_selection=selection_result,
            trace=trace_steps,
            selected_nodes=selected_nodes,
            retrieval_hits=retrieval_hits,
            search_mode=search_mode,
            artifact_root=artifact_root,
            preference_selection_path=preference_selection_path,
            trace_path=trace_path,
            results_path=results_path,
            fell_back_to_base_tree_search=fell_back_to_base_tree_search,
        )
        log_event(
            self._logger,
            "PreferenceAwareTreeSearchCompleted",
            document_id=document_id,
            tree_run_id=tree_run_id,
            search_run_id=request.search_run_id,
            search_mode=search_mode.value,
            selected_snippet_count=len(selection_result.selected_snippets),
            selected_node_count=len(selected_nodes),
            retrieval_hit_count=len(retrieval_hits),
            fell_back_to_base_tree_search=fell_back_to_base_tree_search,
            results_path=results_path,
        )
        return response


__all__ = [
    "PreferenceAwareTreeSearchService",
    "PreferenceRepository",
    "PreferenceSelectionService",
]
