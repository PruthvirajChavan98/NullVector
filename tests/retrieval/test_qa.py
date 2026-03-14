"""QA tests over retrieval hits."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain import (
    AnswerCitation,
    BoundingBox,
    PageSpan,
    VisualRegionReference,
)
from nullvector.llm.multimodal_gateway import (
    MultimodalAssuranceMode,
    MultimodalFailureCategory,
    MultimodalGatewayAuditRecord,
    MultimodalGatewayError,
    MultimodalGatewayFailure,
    RegionImageInput,
)
from nullvector.retrieval import (
    QueryPlanner,
    RetrievalCorpusBuilder,
    RetrievalQAService,
    RetrievalRanker,
    RetrievalService,
    augment_corpus_with_attachments,
    load_retrieval_corpus,
)

from .support import write_synthetic_bundle


def _services(
    *,
    multimodal_service: object | None = None,
) -> tuple[RetrievalService, RetrievalQAService]:
    retrieval_service = RetrievalService(QueryPlanner(), RetrievalRanker())
    return retrieval_service, RetrievalQAService(
        retrieval_service,
        multimodal_service=multimodal_service,
    )


def _multimodal_gateway_error() -> MultimodalGatewayError:
    failure = MultimodalGatewayFailure(
        request_id="request-001",
        operation_name="visual_region_enrichment",
        category=MultimodalFailureCategory.NETWORK_FAILURE,
        message="network failure",
        provider_name="test-provider",
        model_name="test-model",
        assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
    )
    audit_record = MultimodalGatewayAuditRecord(
        audit_id="audit-001",
        request_id="request-001",
        operation_name="visual_region_enrichment",
        provider_name="test-provider",
        model_name="test-model",
        assurance_mode=MultimodalAssuranceMode.ATTACHMENT_ONLY,
        prompt="Describe the image region.",
        regions=(
            RegionImageInput(
                region=VisualRegionReference(
                    document_id="d" * 64,
                    page_index=0,
                    region_id="region-001",
                    bbox=BoundingBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0),
                ),
                image_path="region.png",
            ),
        ),
        failure=failure,
    )
    return MultimodalGatewayError(
        failure,
        audit_record=audit_record,
        audit_path=None,
    )


class _GatewayErrorMultimodalService:
    def enrich(self, _request: object) -> object:
        raise _multimodal_gateway_error()


class _RuntimeErrorMultimodalService:
    def enrich(self, _request: object) -> object:
        raise RuntimeError("boom")


def test_visual_query_without_multimodal_returns_honest_failure(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    corpus = load_retrieval_corpus(manifest.corpus_path)
    _, qa_service = _services()

    response = qa_service.answer(
        corpus=corpus,
        query="what is the image on first page about?",
    )
    expected = (
        "Page 1 contains visual evidence, but no grounded visual interpretation is "
        "available in the current corpus."
    )

    assert response.answer == expected
    assert response.answer_mode == "visual_interpretation_unavailable"
    assert response.citations[0].page_label == "1"


def test_visual_query_multimodal_gateway_error_falls_back_cleanly(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    corpus = load_retrieval_corpus(manifest.corpus_path)
    _, qa_service = _services(multimodal_service=_GatewayErrorMultimodalService())

    response = qa_service.answer(
        corpus=corpus,
        query="what is the image on first page about?",
    )

    assert response.answer_mode == "visual_interpretation_unavailable"
    assert response.answer.startswith("Page 1 contains visual evidence")
    assert response.citations[0].page_label == "1"


def test_visual_query_runtime_error_falls_back_cleanly(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    corpus = load_retrieval_corpus(manifest.corpus_path)
    _, qa_service = _services(multimodal_service=_RuntimeErrorMultimodalService())

    response = qa_service.answer(
        corpus=corpus,
        query="what is the image on first page about?",
    )

    assert response.answer_mode == "visual_interpretation_unavailable"
    assert response.answer.startswith("Page 1 contains visual evidence")
    assert response.citations[0].page_label == "1"


def test_visual_query_with_cached_attachment_returns_grounded_answer(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    corpus = augment_corpus_with_attachments(
        corpus=load_retrieval_corpus(manifest.corpus_path),
        attachments=(bundle.cached_attachment,),
    )
    _, qa_service = _services()

    response = qa_service.answer(
        corpus=corpus,
        query="what is the image on first page about?",
    )

    assert response.answer == bundle.cached_attachment.insight.summary
    assert response.answer_mode == "cached_visual_attachment"


def test_text_query_returns_citations_from_authoritative_units(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    corpus = load_retrieval_corpus(manifest.corpus_path)
    _, qa_service = _services()

    response = qa_service.answer(corpus=corpus, query="Alpha body line")

    assert response.answer_mode == "authoritative_text"
    assert response.citations
    assert response.citations[0].quote is not None
    assert response.citations[0].page_label == "2"
    assert "Alpha body line" in (response.citations[0].quote or "")


def test_answer_citation_formats_multi_page_labels() -> None:
    citation = AnswerCitation(
        document_id="d" * 64,
        unit_id="unit-001",
        page_span=PageSpan(start_page=0, end_page=2),
    )

    assert citation.page_label == "1-3"
    assert citation.page_span == PageSpan(start_page=0, end_page=2)
