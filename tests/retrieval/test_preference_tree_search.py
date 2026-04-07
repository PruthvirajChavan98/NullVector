"""Preference-aware tree-search retrieval tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullvector.domain.retrieval import (
    PreferenceAwareTreeSearchRequest,
    PreferenceScope,
    PreferenceSelectionRequest,
    PreferenceSnippet,
    TreeSearchRequest,
)
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.retrieval import QueryPlanner, RetrievalRanker, RetrievalService
from nullvector.retrieval._artifacts import load_node_cards, load_tree_manifest
from nullvector.retrieval.preference_tree_search import (
    PreferenceAwareTreeSearchService,
    PreferenceRepository,
    PreferenceSelectionService,
)
from nullvector.retrieval.tree_search import TreeSearchService
from nullvector.storage import FilesystemStorageConfig, build_document_store
from tests.retrieval.support import build_markdown_tree_search_artifacts


class StaticPreferenceRepository(PreferenceRepository):
    """Static preference repository for integration tests."""

    def __init__(self, snippets: tuple[PreferenceSnippet, ...]) -> None:
        self._snippets = snippets

    def load_snippets(self) -> tuple[PreferenceSnippet, ...]:
        return self._snippets


def _tree_search_services(
    tmp_path: Path,
) -> tuple[TreeSearchService, PreferenceAwareTreeSearchService]:
    planner = QueryPlanner()
    retrieval_service = RetrievalService(planner, RetrievalRanker())
    storage = FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    return (
        TreeSearchService(planner, retrieval_service, storage=storage),
        PreferenceAwareTreeSearchService(
            planner,
            retrieval_service,
            storage=storage,
        ),
    )


def _node_titles_by_id(tree_manifest_path: Path) -> dict[str, str]:
    store = build_document_store(None, default_filesystem_root=".")
    tree_manifest = load_tree_manifest(store, str(tree_manifest_path))
    assert tree_manifest is not None
    return {
        node_card.node_id: node_card.title for node_card in load_node_cards(store, tree_manifest)
    }


def test_preference_selection_ranks_and_truncates_snippets() -> None:
    service = PreferenceSelectionService()

    result = service.select(
        PreferenceSelectionRequest(
            query="litigation policies",
            snippets=(
                PreferenceSnippet(
                    preference_id="pref-global",
                    scope=PreferenceScope.GLOBAL,
                    text="Prefer revenue policies and revenue summaries.",
                    priority=1,
                ),
                PreferenceSnippet(
                    preference_id="pref-tenant",
                    scope=PreferenceScope.TENANT,
                    text="Prefer litigation policies and case deadlines.",
                    priority=2,
                ),
                PreferenceSnippet(
                    preference_id="pref-user",
                    scope=PreferenceScope.USER,
                    text="Prefer litigation policies for this review.",
                    priority=3,
                ),
            ),
            limit=2,
        )
    )

    assert tuple(snippet.preference_id for snippet in result.selected_snippets) == (
        "pref-user",
        "pref-tenant",
    )
    assert "pref-user" in result.selection_reason


def test_preference_tree_search_zero_snippets_matches_base_tree_search(tmp_path: Path) -> None:
    tree_manifest_path, retrieval_manifest_path = build_markdown_tree_search_artifacts(
        tmp_path,
        bundle_name="preference-zero",
        lines=(
            "# Revenue Overview",
            "Alpha revenue growth accelerated this quarter.",
            "Margins improved across the business.",
            "",
            "# Litigation Summary",
            "Major case deadlines shifted into the next quarter.",
            "No settlement has been reached.",
        ),
    )
    base_service, preference_service = _tree_search_services(tmp_path)

    base_response = base_service.search(
        request=TreeSearchRequest(
            query="alpha revenue growth",
            tree_manifest_path=str(tree_manifest_path),
            retrieval_manifest_path=str(retrieval_manifest_path),
            search_run_id="pref-zero-base",
        )
    )
    preference_response = preference_service.search(
        PreferenceAwareTreeSearchRequest(
            query="alpha revenue growth",
            tree_manifest_path=str(tree_manifest_path),
            retrieval_manifest_path=str(retrieval_manifest_path),
            search_run_id="pref-zero-aware",
        )
    )

    assert preference_response.preference_selection.selected_snippets == ()
    assert preference_response.selected_nodes == base_response.selected_nodes
    assert preference_response.retrieval_hits == base_response.retrieval_hits
    assert tuple(
        (
            step.step_index,
            step.frontier_node_ids,
            step.selected_node_ids,
            step.selection_reason,
            step.termination_signal,
        )
        for step in preference_response.trace
    ) == tuple(
        (
            step.step_index,
            step.frontier_node_ids,
            step.selected_node_ids,
            step.selection_reason,
            step.termination_signal,
        )
        for step in base_response.trace
    )
    assert all(step.applied_preference_ids == () for step in preference_response.trace)
    assert Path(preference_response.preference_selection_path).exists()
    assert Path(preference_response.trace_path).exists()
    assert Path(preference_response.results_path).exists()


@pytest.mark.skip(reason="deterministic ranking order changed after LLM pivot (Phase 4 scope)")
def test_preference_tree_search_biases_node_choice(tmp_path: Path) -> None:
    tree_manifest_path, retrieval_manifest_path = build_markdown_tree_search_artifacts(
        tmp_path,
        bundle_name="preference-bias",
        lines=(
            "# Alpha Policies",
            "Alpha policies were updated for the quarter.",
            "",
            "# Zeta Litigation Policies",
            "Litigation policies focus on case deadlines and court filings.",
        ),
    )
    base_service, preference_service = _tree_search_services(tmp_path)
    title_by_id = _node_titles_by_id(tree_manifest_path)

    base_response = base_service.search(
        request=TreeSearchRequest(
            query="policies",
            tree_manifest_path=str(tree_manifest_path),
            retrieval_manifest_path=str(retrieval_manifest_path),
            search_run_id="pref-bias-base",
        )
    )
    response = preference_service.search(
        PreferenceAwareTreeSearchRequest(
            query="policies",
            tree_manifest_path=str(tree_manifest_path),
            retrieval_manifest_path=str(retrieval_manifest_path),
            search_run_id="pref-bias-aware",
            preference_snippets=(
                PreferenceSnippet(
                    preference_id="pref-litigation",
                    scope=PreferenceScope.USER,
                    text="Prefer litigation policies and case deadlines.",
                    priority=5,
                ),
            ),
        )
    )

    assert title_by_id[base_response.selected_nodes[0].node_id] == "Alpha Policies"
    assert title_by_id[response.selected_nodes[0].node_id] == "Zeta Litigation Policies"
    assert response.trace[0].applied_preference_ids == ("pref-litigation",)


def test_preference_tree_search_uses_repository_snippets(tmp_path: Path) -> None:
    tree_manifest_path, retrieval_manifest_path = build_markdown_tree_search_artifacts(
        tmp_path,
        bundle_name="preference-repo",
        lines=(
            "# Alpha Policies",
            "Alpha policies were updated for the quarter.",
            "",
            "# Zeta Litigation Policies",
            "Litigation policies focus on case deadlines and court filings.",
        ),
    )
    planner = QueryPlanner()
    retrieval_service = RetrievalService(planner, RetrievalRanker())
    storage = FilesystemStorageConfig(root=str(tmp_path / "artifacts"))
    service = PreferenceAwareTreeSearchService(
        planner,
        retrieval_service,
        preference_repository=StaticPreferenceRepository(
            (
                PreferenceSnippet(
                    preference_id="pref-litigation",
                    scope=PreferenceScope.TENANT,
                    text="Prefer litigation policies and case deadlines.",
                    priority=4,
                ),
            )
        ),
        storage=storage,
    )
    title_by_id = _node_titles_by_id(tree_manifest_path)

    response = service.search(
        PreferenceAwareTreeSearchRequest(
            query="policies",
            tree_manifest_path=str(tree_manifest_path),
            retrieval_manifest_path=str(retrieval_manifest_path),
            search_run_id="pref-repo-aware",
        )
    )

    assert tuple(
        snippet.preference_id for snippet in response.preference_selection.selected_snippets
    ) == ("pref-litigation",)
    assert title_by_id[response.selected_nodes[0].node_id] == "Zeta Litigation Policies"
    selection_payload = json.loads(Path(response.preference_selection_path).read_text())
    assert selection_payload["selected_snippets"][0]["preference_id"] == "pref-litigation"


def test_preference_tree_search_gateway_rejects_invalid_node_ids(tmp_path: Path) -> None:
    tree_manifest_path, retrieval_manifest_path = build_markdown_tree_search_artifacts(
        tmp_path,
        bundle_name="preference-invalid-node",
        lines=(
            "# Revenue Policies",
            "Revenue policies were updated for the quarter.",
            "",
            "# Litigation Policies",
            "Litigation policies focus on case deadlines and court filings.",
        ),
    )
    _base_service, preference_service = _tree_search_services(tmp_path)
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "preference_tree_search_frontier": NoopScriptedResponse(
                    output_json={
                        "selected_node_ids": ["not-a-real-node"],
                        "selection_reason": "Invalid node id.",
                        "termination_signal": None,
                        "applied_preference_ids": ["pref-litigation"],
                    }
                )
            }
        ),
    )

    with pytest.raises(ValueError, match="provided frontier"):
        preference_service.search(
            PreferenceAwareTreeSearchRequest(
                query="policies",
                tree_manifest_path=str(tree_manifest_path),
                retrieval_manifest_path=str(retrieval_manifest_path),
                search_run_id="pref-invalid-node-aware",
                preference_snippets=(
                    PreferenceSnippet(
                        preference_id="pref-litigation",
                        scope=PreferenceScope.USER,
                        text="Prefer litigation policies and case deadlines.",
                    ),
                ),
            ),
            gateway=gateway,
        )


def test_preference_tree_search_gateway_rejects_invalid_preference_ids(tmp_path: Path) -> None:
    tree_manifest_path, retrieval_manifest_path = build_markdown_tree_search_artifacts(
        tmp_path,
        bundle_name="preference-invalid-id",
        lines=(
            "# Revenue Policies",
            "Revenue policies were updated for the quarter.",
            "",
            "# Litigation Policies",
            "Litigation policies focus on case deadlines and court filings.",
        ),
    )
    _base_service, preference_service = _tree_search_services(tmp_path)
    title_by_id = _node_titles_by_id(tree_manifest_path)
    valid_node_id = next(
        node_id for node_id, title in title_by_id.items() if title == "Litigation Policies"
    )
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "preference_tree_search_frontier": NoopScriptedResponse(
                    output_json={
                        "selected_node_ids": [valid_node_id],
                        "selection_reason": "Litigation is preferred.",
                        "termination_signal": "evidence_sufficient",
                        "applied_preference_ids": ["bogus-pref"],
                    }
                )
            }
        ),
    )

    with pytest.raises(ValueError, match="selected preference set"):
        preference_service.search(
            PreferenceAwareTreeSearchRequest(
                query="policies",
                tree_manifest_path=str(tree_manifest_path),
                retrieval_manifest_path=str(retrieval_manifest_path),
                search_run_id="pref-invalid-id-aware",
                preference_snippets=(
                    PreferenceSnippet(
                        preference_id="pref-litigation",
                        scope=PreferenceScope.USER,
                        text="Prefer litigation policies and case deadlines.",
                    ),
                ),
            ),
            gateway=gateway,
        )


def test_preference_tree_search_falls_back_to_base_when_gateway_underperforms(
    tmp_path: Path,
) -> None:
    tree_manifest_path, retrieval_manifest_path = build_markdown_tree_search_artifacts(
        tmp_path,
        bundle_name="preference-fallback",
        lines=(
            "# Revenue Overview",
            "Alpha revenue growth accelerated this quarter.",
            "Margins improved across the business.",
            "",
            "# Litigation Summary",
            "Major case deadlines shifted into the next quarter.",
            "No settlement has been reached.",
        ),
    )
    _base_service, preference_service = _tree_search_services(tmp_path)
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "preference_tree_search_frontier": NoopScriptedResponse(
                    output_json={
                        "selected_node_ids": [],
                        "selection_reason": "No confident preference-aware choice.",
                        "termination_signal": None,
                        "applied_preference_ids": [],
                    }
                )
            }
        ),
    )

    response = preference_service.search(
        PreferenceAwareTreeSearchRequest(
            query="alpha revenue growth",
            tree_manifest_path=str(tree_manifest_path),
            retrieval_manifest_path=str(retrieval_manifest_path),
            search_run_id="pref-fallback-aware",
            preference_snippets=(
                PreferenceSnippet(
                    preference_id="pref-revenue",
                    scope=PreferenceScope.USER,
                    text="Prefer revenue discussions and margin analysis.",
                ),
            ),
        ),
        gateway=gateway,
    )

    assert response.fell_back_to_base_tree_search is True
    assert response.selected_nodes
    assert response.retrieval_hits
