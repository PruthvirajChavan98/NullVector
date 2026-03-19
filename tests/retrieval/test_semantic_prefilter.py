"""Semantic proxy building and lexical prefilter tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from nullvector.domain.common import PageSpan
from nullvector.domain.document_selection import (
    DocumentPrefilterHit,
    DocumentPrefilterRequest,
    DocumentSemanticProxy,
    DocumentSemanticProxySource,
)
from nullvector.domain.retrieval import (
    DocumentDescription,
    DocumentDescriptionMethod,
    DocumentDescriptionRequest,
)
from nullvector.domain.tree import NodeCard, NodeSummary, NodeSummaryMethod
from nullvector.retrieval import (
    DocumentDescriptionBuilder,
    DocumentSemanticProxyBuilder,
    LexicalDocumentPrefilter,
    QueryPlanner,
    RetrievalCorpusBuilder,
    RetrievalRanker,
    RetrievalService,
    SemanticPrefilterService,
    load_retrieval_corpus,
)
from nullvector.retrieval.semantic_prefilter import _build_semantic_proxy
from nullvector.storage import FilesystemStorageConfig

from .support import SyntheticRetrievalBundle, write_synthetic_bundle


@dataclass(frozen=True)
class _BundleConfig:
    bundle_name: str
    document_id: str
    display_name: str
    section_title: str
    body_lines: tuple[str, ...]
    summary_text: str
    keywords: tuple[str, ...]


def _source(
    *,
    document_id: str = "a" * 64,
    display_name: str = "Alpha File",
    description_manifest_path: str = "/tmp/description/manifest.json",
    tree_manifest_path: str = "/tmp/tree/manifest.json",
) -> DocumentSemanticProxySource:
    return DocumentSemanticProxySource(
        document_id=document_id,
        display_name=display_name,
        description_manifest_path=description_manifest_path,
        tree_manifest_path=tree_manifest_path,
    )


def _description(
    *,
    document_id: str = "a" * 64,
    tree_manifest_path: str = "/tmp/tree/manifest.json",
    description_text: str = "Alpha description.",
) -> DocumentDescription:
    return DocumentDescription(
        document_id=document_id,
        tree_run_id="tree-run",
        source_manifest_paths=(
            "/tmp/acquisition/manifest.json",
            tree_manifest_path,
        ),
        description_text=description_text,
        description_method=DocumentDescriptionMethod.DETERMINISTIC_FALLBACK,
        source_node_ids=("node-1",),
        settings_digest="d" * 64,
    )


def _node_card(
    *,
    node_id: str,
    title: str,
    path: tuple[str, ...],
    level: int,
    start_page: int,
    end_page: int,
    keywords: tuple[str, ...] = (),
) -> NodeCard:
    return NodeCard(
        node_id=node_id,
        document_id="a" * 64,
        path=path,
        level=level,
        title=title,
        page_span=PageSpan(start_page=start_page, end_page=end_page),
        keywords=keywords,
    )


def _node_summary(
    *,
    node_id: str,
    summary: str,
    keywords: tuple[str, ...] = (),
) -> NodeSummary:
    return NodeSummary(
        node_id=node_id,
        summary=summary,
        keywords=keywords,
        summary_method=NodeSummaryMethod.PASSTHROUGH,
        token_count=10,
        estimated_token_count=10,
        exact_token_count=10,
        tokenizer_identity="synthetic-tokenizer",
    )


def _proxy(
    *,
    document_id: str,
    display_name: str,
    description_text: str,
    summary_text: str,
    keywords: tuple[str, ...],
) -> DocumentSemanticProxy:
    return DocumentSemanticProxy(
        document_id=document_id,
        display_name=display_name,
        description_text=description_text,
        summary_text=summary_text,
        keywords=keywords,
        source_node_ids=("node-1",),
        description_manifest_path=f"/tmp/{document_id}/description/manifest.json",
        tree_manifest_path=f"/tmp/{document_id}/tree/manifest.json",
    )


def _build_proxy_artifacts(
    tmp_path: Path,
) -> tuple[tuple[DocumentSemanticProxy, ...], dict[str, SyntheticRetrievalBundle]]:
    description_builder = DocumentDescriptionBuilder()
    proxy_builder = DocumentSemanticProxyBuilder()
    bundle_configs = (
        _BundleConfig(
            bundle_name="alpha",
            document_id="1" * 64,
            display_name="Alpha Revenue Dossier",
            section_title="Revenue Overview",
            body_lines=("Alpha revenue rose", "Margins improved"),
            summary_text=(
                "Revenue Overview explains alpha revenue growth and margin improvements."
            ),
            keywords=("revenue", "alpha"),
        ),
        _BundleConfig(
            bundle_name="beta",
            document_id="2" * 64,
            display_name="Beta Litigation Memo",
            section_title="Litigation Summary",
            body_lines=("Beta litigation continues", "Case deadlines shifted"),
            summary_text=(
                "Litigation Summary explains beta litigation deadlines and case posture."
            ),
            keywords=("litigation", "beta"),
        ),
    )
    bundles: dict[str, SyntheticRetrievalBundle] = {}
    sources: list[DocumentSemanticProxySource] = []
    for config in bundle_configs:
        bundle = write_synthetic_bundle(
            tmp_path / config.bundle_name,
            document_id=config.document_id,
            bundle_name=config.bundle_name,
            section_title=config.section_title,
            body_lines=config.body_lines,
            summary_text=config.summary_text,
            keywords=config.keywords,
        )
        bundles[config.document_id] = bundle
        manifest = description_builder.build(
            DocumentDescriptionRequest(
                acquisition_manifest_path=str(bundle.acquisition_manifest_path),
                tree_manifest_path=str(bundle.tree_manifest_path),
                description_run_id=f"{config.bundle_name}-description",
            )
        )
        assert manifest.artifact_root is not None
        sources.append(
            DocumentSemanticProxySource(
                document_id=config.document_id,
                display_name=config.display_name,
                description_manifest_path=str(Path(manifest.artifact_root) / "manifest.json"),
                tree_manifest_path=str(bundle.tree_manifest_path),
            )
        )
    return (proxy_builder.build(tuple(sources)), bundles)


def test_build_semantic_proxy_uses_top_level_summaries() -> None:
    tree_manifest_path = "/tmp/tree/manifest.json"
    proxy = _build_semantic_proxy(
        source=_source(tree_manifest_path=tree_manifest_path),
        description=_description(tree_manifest_path=tree_manifest_path),
        description_manifest_path="/tmp/description/manifest.json",
        description_source_tree_manifest_path=tree_manifest_path,
        tree_manifest_path=tree_manifest_path,
        node_cards=(
            _node_card(
                node_id="root",
                title="Root",
                path=("Root",),
                level=1,
                start_page=0,
                end_page=2,
            ),
            _node_card(
                node_id="revenue",
                title="Revenue Overview",
                path=("Root", "Revenue Overview"),
                level=2,
                start_page=1,
                end_page=1,
            ),
            _node_card(
                node_id="litigation",
                title="Litigation Summary",
                path=("Root", "Litigation Summary"),
                level=2,
                start_page=2,
                end_page=2,
            ),
        ),
        node_summaries=(
            _node_summary(
                node_id="revenue",
                summary="Revenue summary from the top-level branch.",
                keywords=("revenue", "alpha"),
            ),
            _node_summary(
                node_id="litigation",
                summary="Litigation summary from the top-level branch.",
                keywords=("litigation", "beta"),
            ),
        ),
    )

    assert proxy.summary_text == (
        "Revenue summary from the top-level branch. Litigation summary from the top-level branch."
    )
    assert proxy.keywords == ("revenue", "alpha", "litigation", "beta")
    assert proxy.source_node_ids == ("revenue", "litigation")


def test_build_semantic_proxy_falls_back_to_top_level_titles_when_summaries_missing() -> None:
    tree_manifest_path = "/tmp/tree/manifest.json"
    proxy = _build_semantic_proxy(
        source=_source(tree_manifest_path=tree_manifest_path),
        description=_description(tree_manifest_path=tree_manifest_path),
        description_manifest_path="/tmp/description/manifest.json",
        description_source_tree_manifest_path=tree_manifest_path,
        tree_manifest_path=tree_manifest_path,
        node_cards=(
            _node_card(
                node_id="revenue",
                title="Revenue Overview",
                path=("Revenue Overview",),
                level=1,
                start_page=1,
                end_page=1,
            ),
            _node_card(
                node_id="litigation",
                title="Litigation Summary",
                path=("Litigation Summary",),
                level=1,
                start_page=2,
                end_page=2,
            ),
        ),
        node_summaries=(),
    )

    assert proxy.summary_text == "Revenue Overview. Litigation Summary."
    assert proxy.keywords == ()
    assert proxy.source_node_ids == ("revenue", "litigation")


def test_build_semantic_proxy_dedupes_and_caps_keywords() -> None:
    tree_manifest_path = "/tmp/tree/manifest.json"
    top_level_cards = tuple(
        _node_card(
            node_id=f"node-{index}",
            title=f"Section {index}",
            path=(f"Section {index}",),
            level=1,
            start_page=index,
            end_page=index,
            keywords=(f"card-{index}", "shared"),
        )
        for index in range(8)
    )
    node_summaries = tuple(
        _node_summary(
            node_id=f"node-{index}",
            summary=f"Summary {index}",
            keywords=(f"summary-{index}", "shared"),
        )
        for index in range(8)
    )

    proxy = _build_semantic_proxy(
        source=_source(tree_manifest_path=tree_manifest_path),
        description=_description(tree_manifest_path=tree_manifest_path),
        description_manifest_path="/tmp/description/manifest.json",
        description_source_tree_manifest_path=tree_manifest_path,
        tree_manifest_path=tree_manifest_path,
        node_cards=top_level_cards,
        node_summaries=node_summaries,
    )

    assert len(proxy.keywords) == 12
    assert proxy.keywords[:9] == (
        "summary-0",
        "shared",
        "summary-1",
        "summary-2",
        "summary-3",
        "summary-4",
        "summary-5",
        "summary-6",
        "summary-7",
    )
    assert proxy.keywords[9:] == ("card-0", "card-1", "card-2")


def test_build_semantic_proxy_rejects_stale_tree_manifest_mismatch() -> None:
    with pytest.raises(ValueError, match="stale for the provided tree manifest"):
        _build_semantic_proxy(
            source=_source(tree_manifest_path="/tmp/tree/current.json"),
            description=_description(tree_manifest_path="/tmp/tree/other.json"),
            description_manifest_path="/tmp/description/manifest.json",
            description_source_tree_manifest_path="/tmp/tree/current.json",
            tree_manifest_path="/tmp/tree/current.json",
            node_cards=(
                _node_card(
                    node_id="revenue",
                    title="Revenue Overview",
                    path=("Revenue Overview",),
                    level=1,
                    start_page=1,
                    end_page=1,
                ),
            ),
            node_summaries=(),
        )


def test_lexical_document_prefilter_ranks_hits_deterministically() -> None:
    engine = LexicalDocumentPrefilter()

    hits = engine.search(
        DocumentPrefilterRequest(
            collection_id="collection-prefilter",
            selection_run_id="prefilter-001",
            query="beta litigation deadlines",
            proxies=(
                _proxy(
                    document_id="doc-alpha",
                    display_name="Alpha Revenue Dossier",
                    description_text="Revenue planning for alpha operations.",
                    summary_text="Revenue summary for alpha growth.",
                    keywords=("revenue", "alpha"),
                ),
                _proxy(
                    document_id="doc-beta",
                    display_name="Beta Litigation Memo",
                    description_text="Litigation summary covering beta deadlines.",
                    summary_text="Case posture and litigation deadlines for beta.",
                    keywords=("litigation", "deadlines"),
                ),
                _proxy(
                    document_id="doc-gamma",
                    display_name="Gamma Note",
                    description_text="General planning memorandum.",
                    summary_text="Operations summary only.",
                    keywords=("operations",),
                ),
            ),
            limit=3,
        )
    )

    assert tuple(hit.document_id for hit in hits) == ("doc-beta", "doc-alpha", "doc-gamma")
    assert hits[0].score > hits[1].score >= hits[2].score


def test_lexical_document_prefilter_keeps_zero_score_hits_only_when_needed() -> None:
    engine = LexicalDocumentPrefilter()

    hits = engine.search(
        DocumentPrefilterRequest(
            collection_id="collection-zero-score",
            selection_run_id="prefilter-002",
            query="beta litigation",
            proxies=(
                _proxy(
                    document_id="doc-match",
                    display_name="Beta Litigation Memo",
                    description_text="Litigation memo for beta.",
                    summary_text="Beta litigation deadlines.",
                    keywords=("litigation",),
                ),
                _proxy(
                    document_id="doc-zero-a",
                    display_name="Alpha Brief",
                    description_text="Revenue only.",
                    summary_text="Revenue only.",
                    keywords=("revenue",),
                ),
                _proxy(
                    document_id="doc-zero-b",
                    display_name="Bravo Brief",
                    description_text="Markets only.",
                    summary_text="Markets only.",
                    keywords=("markets",),
                ),
            ),
            limit=2,
        )
    )

    assert tuple(hit.document_id for hit in hits) == ("doc-match", "doc-zero-a")
    assert hits[1].score == 0.0


def test_lexical_document_prefilter_reports_matched_proxy_fields() -> None:
    engine = LexicalDocumentPrefilter()

    hits = engine.search(
        DocumentPrefilterRequest(
            collection_id="collection-fields",
            selection_run_id="prefilter-003",
            query="beta litigation deadlines",
            proxies=(
                _proxy(
                    document_id="doc-beta",
                    display_name="Beta Litigation Memo",
                    description_text="Litigation summary covering deadlines.",
                    summary_text="Deadlines and case posture.",
                    keywords=("litigation", "beta"),
                ),
            ),
            limit=1,
        )
    )

    assert hits[0].matched_proxy_fields == (
        "display_name",
        "description_text",
        "summary_text",
        "keywords",
    )


def test_semantic_prefilter_service_accepts_fake_engine_and_persists_artifacts(
    tmp_path: Path,
) -> None:
    class _FakeEngine:
        def search(
            self,
            request: DocumentPrefilterRequest,
        ) -> tuple[DocumentPrefilterHit, ...]:
            assert request.proxies
            return (
                DocumentPrefilterHit(
                    document_id=request.proxies[0].document_id,
                    score=7.5,
                    matched_proxy_fields=("description_text",),
                ),
            )

    service = SemanticPrefilterService(
        engine=_FakeEngine(),
        storage=FilesystemStorageConfig(root=str(tmp_path / "artifacts")),
    )

    response = service.select(
        DocumentPrefilterRequest(
            collection_id="collection-engine",
            selection_run_id="prefilter-004",
            query="alpha",
            proxies=(
                _proxy(
                    document_id="doc-alpha",
                    display_name="Alpha File",
                    description_text="Alpha description.",
                    summary_text="Alpha summary.",
                    keywords=("alpha",),
                ),
            ),
            limit=1,
        )
    )

    index_payload = (
        Path(response.semantic_proxy_index_path).read_text(encoding="utf-8").splitlines()
    )
    results_payload = json.loads(
        Path(response.semantic_prefilter_results_path).read_text(encoding="utf-8")
    )

    assert len(index_payload) == 1
    assert results_payload["hits"][0]["document_id"] == "doc-alpha"
    assert response.hits[0].score == 7.5


def test_document_semantic_proxy_builder_builds_from_description_artifacts(
    tmp_path: Path,
) -> None:
    proxies, _bundles = _build_proxy_artifacts(tmp_path)

    assert tuple(proxy.document_id for proxy in proxies) == ("1" * 64, "2" * 64)
    assert proxies[0].description_text
    assert proxies[1].summary_text
    assert proxies[0].source_node_ids


def test_semantic_prefilter_selects_top_document_and_hands_off_to_retrieval(
    tmp_path: Path,
) -> None:
    proxies, bundles = _build_proxy_artifacts(tmp_path)
    service = SemanticPrefilterService(
        storage=FilesystemStorageConfig(root=str(tmp_path / "selection-artifacts"))
    )

    response = service.select(
        DocumentPrefilterRequest(
            collection_id="collection-handoff",
            selection_run_id="prefilter-005",
            query="beta litigation deadlines",
            proxies=proxies,
            limit=2,
        )
    )

    assert tuple(hit.document_id for hit in response.hits)[:1] == ("2" * 64,)

    selected_bundle = bundles[response.hits[0].document_id]
    retrieval_manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(selected_bundle.acquisition_manifest_path),
        tree_manifest_path=str(selected_bundle.tree_manifest_path),
    )
    retrieval_corpus = load_retrieval_corpus(retrieval_manifest.corpus_path)
    retrieval_hits = RetrievalService(QueryPlanner(), RetrievalRanker()).search(
        corpus=retrieval_corpus,
        query="beta litigation deadlines",
        limit=3,
    )
    persisted_results = json.loads(
        Path(response.semantic_prefilter_results_path).read_text(encoding="utf-8")
    )

    assert retrieval_hits
    assert retrieval_hits[0].unit.document_id == ("2" * 64)
    assert persisted_results["hits"][0]["document_id"] == ("2" * 64)
