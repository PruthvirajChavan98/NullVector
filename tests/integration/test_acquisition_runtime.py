"""Integration coverage for the parallel v2 acquisition + projection runtime."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

import pytest

from nullvector import async_acquire_batch, async_build_tree_batch
from nullvector.domain import (
    AcquisitionRequest,
    AcquisitionSettings,
    DescriptionSelectionRequest,
    DocumentDescriptionRecord,
    DocumentDescriptionRequest,
    DocumentFilterClause,
    DocumentFilterOperator,
    DocumentMetadataRecord,
    DocumentPrefilterRequest,
    DocumentSemanticProxySource,
    MarkdownAcquisitionSettings,
    MetadataSelectionPlan,
    MetadataSelectionRequest,
    PreferenceAwareTreeSearchRequest,
    PreferenceScope,
    PreferenceSnippet,
    SourceDocumentKind,
    TreeBuildRequest,
    TreeSearchRequest,
)
from nullvector.ingest.acquisition_service import acquire_document
from nullvector.ingest.errors import ParseConflictError
from nullvector.observability import configure_jsonl_logger
from nullvector.retrieval import (
    DescriptionSelectionService,
    DocumentDescriptionBuilder,
    DocumentSemanticProxyBuilder,
    MetadataSelectionService,
    PreferenceAwareTreeSearchService,
    QueryPlanner,
    RetrievalCorpusBuilder,
    RetrievalQAService,
    RetrievalRanker,
    RetrievalService,
    SemanticPrefilterService,
    TreeSearchService,
    load_document_description,
    load_document_description_manifest,
    load_retrieval_corpus,
)
from nullvector.tree import build_tree

PHASE01_FIXTURES = Path("fixtures/pdfs/phase01")


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_markdown_fixture(path: Path) -> Path:
    path.write_text(
        "\n".join(
            (
                "# Overview",
                "NullVector ingests authored Markdown directly.",
                "",
                "## Details ##",
                "This section exists to verify heading normalization.",
                "",
                "---",
                "### Appendix",
                "```python",
                "print('stable notebook smoke')",
                "```",
                "",
                "Final notes stay in plain text.",
            )
        ),
        encoding="utf-8",
    )
    return path


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        payload = getattr(record, "nullvector_event", None)
        if isinstance(payload, dict):
            self.events.append(payload)


@pytest.mark.integration
def test_acquisition_runtime_persists_ledger_projection_and_outline_artifacts(
    tmp_path: Path,
) -> None:
    manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(PHASE01_FIXTURES / "born_digital_with_outline.pdf"),
            acquisition_run_id="acquisition-outline-smoke",
            artifact_root=str(tmp_path / "acquisition-runs"),
        )
    )

    ledger = cast(dict[str, Any], _load_json(manifest.ledger_path))
    projection = cast(dict[str, Any], _load_json(manifest.projection_view_path or ""))
    selected_outline = cast(dict[str, Any], _load_json(manifest.selected_outline_path))
    assert manifest.artifact_root is not None
    run_index = cast(
        dict[str, Any],
        _load_json(str(Path(manifest.artifact_root).parent / "run-index.json")),
    )

    assert Path(manifest.ledger_path).exists()
    assert Path(manifest.projection_view_path or "").exists()
    assert Path(manifest.selected_outline_path).exists()
    assert Path(manifest.event_stream_path).exists()
    assert run_index["run_id"] == "acquisition-outline-smoke"
    assert ledger["document_id"] == manifest.document_id
    assert projection["document_id"] == manifest.document_id
    assert len(projection["pages"]) == manifest.page_count
    assert selected_outline["selected_source"] == manifest.selected_outline_source.value
    assert any(page["lines"] for page in projection["pages"])


@pytest.mark.integration
def test_acquisition_runtime_persists_canonical_text_substrate_without_outline_augmentation(
    tmp_path: Path,
) -> None:
    manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(PHASE01_FIXTURES / "born_digital_with_outline.pdf"),
            acquisition_run_id="acquisition-canonical-text",
            artifact_root=str(tmp_path / "acquisition-runs"),
        )
    )

    substrate = cast(dict[str, Any], _load_json(manifest.canonical_text_substrate_path or ""))
    selected_outline = cast(dict[str, Any], _load_json(manifest.selected_outline_path))

    page_one = cast(dict[str, Any], substrate["pages"][1])
    page_one_lines = cast(list[dict[str, Any]], page_one["lines"])

    assert page_one["text"] == "\n".join(line["content"] for line in page_one_lines)
    assert "Details" not in [line["content"] for line in page_one_lines]
    assert selected_outline["entries"][1]["title"] == "Details"


@pytest.mark.integration
def test_acquisition_run_is_idempotent_and_conflicts_on_changed_input(tmp_path: Path) -> None:
    request = AcquisitionRequest(
        source_path=str(PHASE01_FIXTURES / "born_digital_with_outline.pdf"),
        acquisition_run_id="acquisition-idempotent",
        artifact_root=str(tmp_path / "acquisition-runs"),
    )

    first = acquire_document(request)
    second = acquire_document(request)

    assert first == second

    with pytest.raises(ParseConflictError):
        acquire_document(
            request.model_copy(
                update={
                    "source_path": str(PHASE01_FIXTURES / "born_digital_without_outline.pdf"),
                }
            )
        )

    with pytest.raises(ParseConflictError):
        acquire_document(
            request.model_copy(
                update={
                    "settings": request.settings.model_copy(update={"detect_tables": False}),
                }
            )
        )


@pytest.mark.integration
def test_tree_build_accepts_acquisition_manifest(tmp_path: Path) -> None:
    pdf_path = PHASE01_FIXTURES / "born_digital_with_outline.pdf"
    acquisition_manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(pdf_path),
            acquisition_run_id="tree-acquisition-path",
            artifact_root=str(tmp_path / "acquisition-runs"),
        )
    )
    assert acquisition_manifest.artifact_root is not None
    acquisition_tree = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(
                Path(acquisition_manifest.artifact_root) / "manifest.json"
            ),
            tree_run_id="acquisition-tree-build",
        )
    )

    assert acquisition_tree.node_cards_path is not None
    assert acquisition_tree.verification_report_path is not None
    acquisition_cards = cast(list[dict[str, Any]], _load_json(acquisition_tree.node_cards_path))
    verification_report = cast(
        dict[str, Any], _load_json(acquisition_tree.verification_report_path)
    )

    assert acquisition_tree.acquisition_manifest_path == str(
        Path(acquisition_manifest.artifact_root) / "manifest.json"
    )
    assert acquisition_tree.acquisition_artifact_identity == str(
        Path(acquisition_manifest.artifact_root) / "manifest.json"
    )
    assert [card["title"] for card in acquisition_cards] == [
        "Overview",
        "Appendix",
    ]
    assert [issue["code"] for issue in verification_report["document_issues"]] == [
        "page-present-but-title-not-visible"
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_acquisition_and_tree_batch_succeed_on_pdf_fixture(tmp_path: Path) -> None:
    pdf_path = PHASE01_FIXTURES / "born_digital_with_outline.pdf"

    acquisition_result = await async_acquire_batch(
        (
            AcquisitionRequest(
                source_path=str(pdf_path),
                acquisition_run_id="async-acquisition-batch",
                artifact_root=str(tmp_path / "acquisition-runs"),
            ),
        ),
        max_workers=1,
    )

    assert acquisition_result.failed == ()
    assert len(acquisition_result.successful) == 1
    acquisition_manifest = acquisition_result.successful[0]
    assert acquisition_manifest.artifact_root is not None

    tree_result = await async_build_tree_batch(
        (
            TreeBuildRequest(
                acquisition_manifest_path=str(
                    Path(acquisition_manifest.artifact_root) / "manifest.json"
                ),
                tree_run_id="async-tree-build-batch",
                summarize=False,
            ),
        ),
        max_workers=1,
    )

    assert tree_result.failed == ()
    assert len(tree_result.successful) == 1
    tree_manifest = tree_result.successful[0]
    assert tree_manifest.node_cards_path is not None
    assert Path(tree_manifest.node_cards_path).exists()


@pytest.mark.integration
def test_markdown_acquisition_tree_build_and_retrieval_corpus_succeed(tmp_path: Path) -> None:
    markdown_path = _write_markdown_fixture(tmp_path / "authored.md")
    manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(markdown_path),
            acquisition_run_id="markdown-acquisition-smoke",
            artifact_root=str(tmp_path / "acquisition-runs"),
            source_kind=SourceDocumentKind.MARKDOWN,
            provider_identity="markdown_native",
            settings=AcquisitionSettings(
                markdown=MarkdownAcquisitionSettings(
                    max_logical_lines_per_page=5,
                    split_on_thematic_breaks=True,
                )
            ),
        )
    )

    ledger = cast(dict[str, Any], _load_json(manifest.ledger_path))
    selected_outline = cast(dict[str, Any], _load_json(manifest.selected_outline_path))
    tree_manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(Path(manifest.artifact_root or "") / "manifest.json"),
            tree_run_id="markdown-tree-build",
            summarize=False,
        )
    )
    assert tree_manifest.artifact_root is not None
    retrieval_manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(Path(manifest.artifact_root or "") / "manifest.json"),
        tree_manifest_path=str(Path(tree_manifest.artifact_root) / "manifest.json"),
    )
    retrieval_corpus = cast(dict[str, Any], _load_json(retrieval_manifest.corpus_path))

    assert manifest.source_copy_path.endswith("source/original.md")
    assert manifest.selected_outline_source.value == "markdown"
    assert manifest.page_count == 2
    assert selected_outline["selected_source"] == "markdown"
    assert [entry["title"] for entry in selected_outline["entries"]] == [
        "Overview",
        "Details",
        "Appendix",
    ]
    first_page_lines = [
        block["content"]
        for block in cast(list[dict[str, Any]], ledger["pages"][0]["blocks"])
        if block["block_type"] == "line_block"
    ]
    assert "# Overview" not in first_page_lines
    assert "Overview" in first_page_lines
    assert any(unit["unit_type"] == "node_text" for unit in retrieval_corpus["units"])


@pytest.mark.integration
def test_acquisition_and_tree_build_emit_expected_events(tmp_path: Path) -> None:
    logger = logging.getLogger("nullvector.test.acquisition")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    capture = _CaptureHandler()
    logger.addHandler(capture)
    manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(PHASE01_FIXTURES / "born_digital_with_outline.pdf"),
            acquisition_run_id="evented-acquisition",
            artifact_root=str(tmp_path / "acquisition-runs"),
        ),
        logger=logger,
    )

    assert manifest.artifact_root is not None
    build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(Path(manifest.artifact_root) / "manifest.json"),
            tree_run_id="evented-tree-build",
            summarize=False,
        ),
        logger=logger,
    )

    event_names = [str(event["event_name"]) for event in capture.events]

    assert event_names[:2] == [
        "SourceFingerprintComputed",
        "AcquisitionStarted",
    ]
    assert "ProjectionCreated" in event_names
    assert "HierarchyStrategySelected" in event_names
    assert "NodeCommitted" in event_names


@pytest.mark.integration
def test_retrieval_runtime_emits_selection_search_and_qa_events(tmp_path: Path) -> None:
    logger = logging.getLogger("nullvector.test.retrieval_runtime")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    capture = _CaptureHandler()
    logger.addHandler(capture)
    configure_jsonl_logger(str(tmp_path / "observability" / "events.jsonl"), logger=logger)

    markdown_path = _write_markdown_fixture(tmp_path / "runtime-observability.md")
    acquisition_manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(markdown_path),
            acquisition_run_id="runtime-observe-acquisition",
            artifact_root=str(tmp_path / "acquisition-runs"),
            source_kind=SourceDocumentKind.MARKDOWN,
            provider_identity="markdown_native",
            settings=AcquisitionSettings(
                markdown=MarkdownAcquisitionSettings(
                    max_logical_lines_per_page=5,
                    split_on_thematic_breaks=True,
                )
            ),
        ),
        logger=logger,
    )
    assert acquisition_manifest.artifact_root is not None
    acquisition_manifest_path = str(Path(acquisition_manifest.artifact_root) / "manifest.json")

    tree_manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=acquisition_manifest_path,
            tree_run_id="runtime-observe-tree",
            summarize=False,
        ),
        logger=logger,
    )
    assert tree_manifest.artifact_root is not None
    tree_manifest_path = str(Path(tree_manifest.artifact_root) / "manifest.json")

    retrieval_manifest = RetrievalCorpusBuilder(logger=logger).build(
        acquisition_manifest_path=acquisition_manifest_path,
        tree_manifest_path=tree_manifest_path,
        retrieval_run_id="runtime-observe-retrieval",
    )
    corpus = load_retrieval_corpus(retrieval_manifest.corpus_path)

    description_manifest = DocumentDescriptionBuilder(logger=logger).build(
        DocumentDescriptionRequest(
            acquisition_manifest_path=acquisition_manifest_path,
            tree_manifest_path=tree_manifest_path,
            description_run_id="runtime-observe-description",
        )
    )
    description_manifest_loaded = load_document_description_manifest(
        Path(description_manifest.artifact_root or "") / "manifest.json"
    )
    description = load_document_description(description_manifest_loaded.description_path)

    metadata_response = MetadataSelectionService(logger=logger).select(
        MetadataSelectionRequest(
            collection_id="runtime-observe-collection",
            selection_run_id="runtime-observe-metadata",
            plan=MetadataSelectionPlan(
                raw_query="markdown appendix",
                normalized_query="markdown appendix",
                clauses=(
                    DocumentFilterClause(
                        field="source_kind",
                        operator=DocumentFilterOperator.EQ,
                        value="markdown",
                    ),
                ),
            ),
            allowed_fields=("source_kind", "topic"),
            metadata_records=(
                DocumentMetadataRecord(
                    document_id=acquisition_manifest.document_id,
                    display_name="Runtime Observability Markdown",
                    attributes={
                        "source_kind": "markdown",
                        "topic": "appendix and details",
                    },
                ),
            ),
            limit=2,
        )
    )

    description_response = DescriptionSelectionService(logger=logger).select(
        DescriptionSelectionRequest(
            collection_id="runtime-observe-collection",
            selection_run_id="runtime-observe-description-select",
            query="appendix details",
            descriptions=(
                DocumentDescriptionRecord(
                    document_id=acquisition_manifest.document_id,
                    display_name="Runtime Observability Markdown",
                    description_text=description.description_text,
                    description_manifest_path=str(
                        Path(description_manifest.artifact_root or "") / "manifest.json"
                    ),
                ),
            ),
            limit=2,
        )
    )

    semantic_proxies = DocumentSemanticProxyBuilder(logger=logger).build(
        (
            DocumentSemanticProxySource(
                document_id=acquisition_manifest.document_id,
                display_name="Runtime Observability Markdown",
                description_manifest_path=str(
                    Path(description_manifest.artifact_root or "") / "manifest.json"
                ),
                tree_manifest_path=tree_manifest_path,
            ),
        )
    )
    semantic_prefilter_response = SemanticPrefilterService(logger=logger).select(
        DocumentPrefilterRequest(
            collection_id="runtime-observe-collection",
            selection_run_id="runtime-observe-prefilter",
            query="appendix details",
            proxies=semantic_proxies,
            limit=2,
        )
    )

    planner = QueryPlanner()
    retrieval_service = RetrievalService(planner, RetrievalRanker(), logger=logger)
    retrieval_hits = retrieval_service.search(corpus=corpus, query="appendix", limit=3)
    tree_search_response = TreeSearchService(
        planner,
        retrieval_service,
        logger=logger,
    ).search(
        TreeSearchRequest(
            query="appendix",
            tree_manifest_path=tree_manifest_path,
            retrieval_manifest_path=str(
                Path(retrieval_manifest.artifact_root or "") / "manifest.json"
            ),
            search_run_id="runtime-observe-tree-search",
            max_selected_nodes=1,
            retrieval_limit=3,
        )
    )
    preference_response = PreferenceAwareTreeSearchService(
        planner,
        retrieval_service,
        logger=logger,
    ).search(
        PreferenceAwareTreeSearchRequest(
            query="appendix",
            tree_manifest_path=tree_manifest_path,
            retrieval_manifest_path=str(
                Path(retrieval_manifest.artifact_root or "") / "manifest.json"
            ),
            search_run_id="runtime-observe-preference-search",
            max_selected_nodes=1,
            retrieval_limit=3,
            preference_snippets=(
                PreferenceSnippet(
                    preference_id="prefer-appendix",
                    scope=PreferenceScope.USER,
                    text="Prefer appendix sections and appendix details.",
                    priority=5,
                ),
            ),
        )
    )
    qa_response = RetrievalQAService(retrieval_service, logger=logger).answer(
        corpus=corpus,
        query="appendix",
        limit=3,
    )

    event_names = {str(event["event_name"]) for event in capture.events}
    jsonl_events = [
        json.loads(line)
        for line in (tmp_path / "observability" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    jsonl_event_names = {str(event["event_name"]) for event in jsonl_events}

    assert metadata_response.candidates
    assert description_response.candidates
    assert semantic_prefilter_response.hits
    assert retrieval_hits
    assert tree_search_response.retrieval_hits
    assert preference_response.retrieval_hits
    assert qa_response.answer_mode
    assert {
        "AcquisitionCompleted",
        "TreeBuildCompleted",
        "RetrievalCorpusBuildStarted",
        "RetrievalCorpusBuildCompleted",
        "DocumentDescriptionBuildStarted",
        "DocumentDescriptionBuildCompleted",
        "MetadataSelectionStarted",
        "MetadataSelectionCompleted",
        "DescriptionSelectionStarted",
        "DescriptionSelectionCompleted",
        "SemanticProxyBuildStarted",
        "SemanticProxyBuildCompleted",
        "SemanticPrefilterStarted",
        "SemanticPrefilterCompleted",
        "RetrievalSearchStarted",
        "RetrievalSearchCompleted",
        "TreeSearchStarted",
        "TreeSearchStepSelected",
        "TreeSearchCompleted",
        "PreferenceSelectionStarted",
        "PreferenceSelectionCompleted",
        "PreferenceAwareTreeSearchCompleted",
        "RetrievalQAStarted",
        "RetrievalQACompleted",
    }.issubset(event_names)
    assert {"RetrievalQACompleted", "TreeSearchCompleted", "MetadataSelectionCompleted"}.issubset(
        jsonl_event_names
    )


@pytest.mark.integration
@pytest.mark.parametrize("fixture_name", ["scanned_subset.pdf", "mixed_content.pdf"])
def test_visual_regions_persist_real_attachment_assets(
    tmp_path: Path,
    fixture_name: str,
) -> None:
    request = AcquisitionRequest(
        source_path=str(PHASE01_FIXTURES / fixture_name),
        acquisition_run_id=f"visual-assets-{fixture_name.replace('.', '-')}",
        artifact_root=str(tmp_path / "acquisition-runs"),
    )

    first = acquire_document(request)
    second = acquire_document(request)
    first_ledger = cast(dict[str, Any], _load_json(first.ledger_path))
    second_ledger = cast(dict[str, Any], _load_json(second.ledger_path))

    first_assets: list[tuple[str, str, str]] = []
    second_assets: list[tuple[str, str, str]] = []

    for ledger, sink in ((first_ledger, first_assets), (second_ledger, second_assets)):
        for page in cast(list[dict[str, Any]], ledger["pages"]):
            page_blocks = cast(list[dict[str, Any]], page["blocks"])
            reading_indexes = [block["reading_index"] for block in page_blocks]
            assert reading_indexes == list(range(len(page_blocks)))
            for block in page_blocks:
                if block["block_type"] == "visual_artifact" and block["needs_enrichment"]:
                    assert block["asset_path"]
                    assert block["page_render_path"]
                    assert block["coordinate_space"] == "unrotated_page"
                    assert block["render_dpi"] == first.settings.render_dpi
                    assert Path(block["asset_path"]).exists()
                    assert Path(block["page_render_path"]).exists()
                    sink.append(
                        (
                            block["visual_id"],
                            block["asset_path"],
                            block["page_render_path"],
                        )
                    )
                if block["block_type"] == "unresolved_region":
                    assert block["asset_path"]
                    assert block["page_render_path"]
                    assert block["coordinate_space"] == "unrotated_page"
                    assert block["render_dpi"] == first.settings.render_dpi
                    assert Path(block["asset_path"]).exists()
                    assert Path(block["page_render_path"]).exists()
                    sink.append(
                        (
                            block["region_id"],
                            block["asset_path"],
                            block["page_render_path"],
                        )
                    )

    assert first_assets
    assert first_assets == second_assets
