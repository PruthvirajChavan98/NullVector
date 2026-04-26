"""Tree-guided retrieval over persisted node cards, summaries, and retrieval evidence."""

from __future__ import annotations

from logging import Logger

from nullvector.domain.retrieval import (
    TreeSearchFrontierNode,
    TreeSearchMode,
    TreeSearchRequest,
    TreeSearchResponse,
    TreeSearchTraceStep,
)
from nullvector.llm.prompts.tree_search import (
    TreeSearchFrontierPromptResponse,
    build_tree_search_frontier_messages,
)
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.retrieval._tree_search_runtime import (
    FrontierSelectionDecision,
    artifact_path,
    deterministic_selection,
    execute_tree_search,
    load_tree_search_state,
    tree_search_artifact_root,
)
from nullvector.retrieval.llm_planner import LLMQueryPlanner as QueryPlanner
from nullvector.retrieval.service import RetrievalService
from nullvector.storage import StorageConfig, build_document_store


def _gateway_selection(
    frontier_nodes: tuple[TreeSearchFrontierNode, ...],
    *,
    request: TreeSearchRequest,
    normalized_query: str,
    current_depth: int,
    gateway: StructuredLLMGateway,
) -> FrontierSelectionDecision:
    gateway_result = gateway.invoke(
        GatewayRequest[TreeSearchFrontierPromptResponse](
            operation_name="tree_search_frontier",
            messages=build_tree_search_frontier_messages(
                query=request.query,
                normalized_query=normalized_query,
                frontier_nodes=tuple(node.model_dump(mode="json") for node in frontier_nodes),
                current_depth=current_depth,
                max_depth=request.max_depth,
            ),
            response_model=TreeSearchFrontierPromptResponse,
            max_output_tokens=250,
            metadata={
                "query": request.query,
                "current_depth": current_depth,
                "max_depth": request.max_depth,
                "frontier_count": len(frontier_nodes),
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
            "tree_search_frontier returned node_ids outside the provided frontier: "
            f"{invalid_node_ids}"
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
    )


class TreeSearchService:
    """Tree-guided retrieval that narrows the corpus before ranking evidence."""

    def __init__(
        self,
        planner: QueryPlanner,
        retrieval_service: RetrievalService,
        *,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._planner = planner
        self._retrieval_service = retrieval_service
        self._logger = resolve_runtime_logger(logger)
        self._storage = storage

    def search(
        self,
        request: TreeSearchRequest,
        *,
        gateway: StructuredLLMGateway | None = None,
    ) -> TreeSearchResponse:
        state = load_tree_search_state(
            request=request,
            planner=self._planner,
            storage=self._storage,
        )
        search_mode = TreeSearchMode.LLM if gateway is not None else TreeSearchMode.DETERMINISTIC
        log_event(
            self._logger,
            "TreeSearchStarted",
            document_id=state.tree_manifest.document_id,
            tree_run_id=state.tree_manifest.tree_run_id,
            search_run_id=request.search_run_id,
            query=request.query,
            search_mode=search_mode.value,
            max_depth=request.max_depth,
        )
        execution = execute_tree_search(
            state=state,
            request=request,
            retrieval_service=self._retrieval_service,
            search_mode=search_mode,
            frontier_selector=(
                (
                    lambda frontier_nodes, current_depth: _gateway_selection(
                        frontier_nodes,
                        request=request,
                        normalized_query=state.plan.normalized_query,
                        current_depth=current_depth,
                        gateway=gateway,
                    )
                )
                if gateway is not None
                else (
                    lambda frontier_nodes, _unused_depth: deterministic_selection(
                        frontier_nodes,
                        plan=state.plan,
                        query_tokens=state.query_tokens,
                    )
                )
            ),
        )
        store = build_document_store(self._storage, default_filesystem_root=".")
        artifact_root = tree_search_artifact_root(
            request=request,
            tree_run_id=state.tree_manifest.tree_run_id,
            store=store,
        )
        trace_steps = tuple(
            TreeSearchTraceStep(
                step_index=step.step_index,
                frontier_node_ids=step.frontier_node_ids,
                selected_node_ids=step.selected_node_ids,
                selection_reason=step.selection_reason,
                termination_signal=step.termination_signal,
            )
            for step in execution.trace_steps
        )
        for step in trace_steps:
            log_event(
                self._logger,
                "TreeSearchStepSelected",
                document_id=state.tree_manifest.document_id,
                tree_run_id=state.tree_manifest.tree_run_id,
                search_run_id=request.search_run_id,
                step_index=step.step_index,
                frontier_node_ids=step.frontier_node_ids,
                selected_node_ids=step.selected_node_ids,
                termination_signal=(
                    step.termination_signal.value if step.termination_signal is not None else None
                ),
            )

        store = build_document_store(self._storage, default_filesystem_root=".")
        trace_path = store.put_json_artifact(
            run_type="tree_search",
            run_id=request.search_run_id,
            document_id=state.tree_manifest.document_id,
            artifact_kind="tree_search",
            artifact_path=artifact_path(artifact_root, "trace.json"),
            payload={
                "tree_run_id": state.tree_manifest.tree_run_id,
                "document_id": state.tree_manifest.document_id,
                "search_mode": execution.search_mode.value,
                "trace": tuple(step.model_dump(mode="json") for step in trace_steps),
            },
        )
        results_path = store.put_json_artifact(
            run_type="tree_search",
            run_id=request.search_run_id,
            document_id=state.tree_manifest.document_id,
            artifact_kind="tree_search",
            artifact_path=artifact_path(artifact_root, "results.json"),
            payload={
                "tree_run_id": state.tree_manifest.tree_run_id,
                "document_id": state.tree_manifest.document_id,
                "search_mode": execution.search_mode.value,
                "query": request.query,
                "selected_nodes": tuple(
                    candidate.model_dump(mode="json") for candidate in execution.selected_nodes
                ),
                "retrieval_hits": tuple(
                    hit.model_dump(mode="json") for hit in execution.retrieval_hits
                ),
            },
        )
        response = TreeSearchResponse(
            tree_run_id=state.tree_manifest.tree_run_id,
            document_id=state.tree_manifest.document_id,
            trace=trace_steps,
            selected_nodes=execution.selected_nodes,
            retrieval_hits=execution.retrieval_hits,
            search_mode=execution.search_mode,
            artifact_root=artifact_root,
            trace_path=trace_path,
            results_path=results_path,
        )
        log_event(
            self._logger,
            "TreeSearchCompleted",
            document_id=state.tree_manifest.document_id,
            tree_run_id=state.tree_manifest.tree_run_id,
            search_run_id=request.search_run_id,
            search_mode=execution.search_mode.value,
            selected_node_count=len(execution.selected_nodes),
            retrieval_hit_count=len(execution.retrieval_hits),
            trace_path=trace_path,
            results_path=results_path,
        )
        return response


__all__ = ["TreeSearchService"]
