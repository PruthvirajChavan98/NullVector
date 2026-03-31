"""QA tests over retrieval hits."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from nullvector.domain import (
    AnswerCitation,
    BoundingBox,
    DocumentDescription,
    DocumentDescriptionMethod,
    PageSpan,
    VisualRegionReference,
)
from nullvector.llm import (
    GatewayAssuranceMode,
    GatewayAuditRecord,
    GatewayError,
    GatewayFailure,
    GatewayFailureCategory,
    LLMMessage,
    LLMRole,
    RegionImageInput,
    StructuredOutputMode,
)
from nullvector.llm.protocols import StructuredLLMGateway
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
    gateway: object | None = None,
    document_description: DocumentDescription | None = None,
) -> tuple[RetrievalService, RetrievalQAService]:
    retrieval_service = RetrievalService(QueryPlanner(), RetrievalRanker())
    return retrieval_service, RetrievalQAService(
        retrieval_service,
        gateway=cast(StructuredLLMGateway | None, gateway),
        document_description=document_description,
    )


def _gateway_error() -> GatewayError:
    failure = GatewayFailure(
        request_id="request-001",
        operation_name="visual_region_enrichment",
        category=GatewayFailureCategory.NETWORK_FAILURE,
        message="network failure",
        provider_name="test-provider",
        model_name="test-model",
        assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
        structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
        retryable=False,
        attempt_count=1,
    )
    audit_record = GatewayAuditRecord(
        audit_id="audit-001",
        request_id="request-001",
        operation_name="visual_region_enrichment",
        provider_name="test-provider",
        model_name="test-model",
        assurance_mode=GatewayAssuranceMode.TRANSPORT_COMPATIBLE,
        structured_output_mode=StructuredOutputMode.TRANSPORT_COMPATIBLE,
        messages=(LLMMessage(role=LLMRole.USER, content="Describe the image region."),),
        attachments=(
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
        attempts=(),
    )
    return GatewayError(
        failure,
        audit_record=audit_record,
        audit_path=None,
    )


class _GatewayErrorGateway:
    def invoke(self, _request: object) -> object:
        raise _gateway_error()


class _RuntimeErrorGateway:
    def invoke(self, _request: object) -> object:
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
    _, qa_service = _services(gateway=_GatewayErrorGateway())

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
    _, qa_service = _services(gateway=_RuntimeErrorGateway())

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


def test_document_summary_query_prefers_grounded_document_description(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    corpus = load_retrieval_corpus(manifest.corpus_path)
    _, qa_service = _services(
        document_description=DocumentDescription(
            document_id=bundle.document_id,
            tree_run_id="synthetic-tree-run",
            source_manifest_paths=(
                str(bundle.acquisition_manifest_path),
                str(bundle.tree_manifest_path),
            ),
            description_text="This document explains appendix-level policy guidance.",
            description_method=DocumentDescriptionMethod.DETERMINISTIC_FALLBACK,
            source_node_ids=("node-appendix-a",),
            settings_digest="d" * 64,
        )
    )

    response = qa_service.answer(corpus=corpus, query="what is this document about?")

    assert response.answer_mode == "document_summary_description"
    assert response.answer_strategy == "document_description"
    assert response.answer == "This document explains appendix-level policy guidance."
    assert response.citations == ()


def test_low_signal_text_query_returns_low_evidence_instead_of_forced_excerpt(
    tmp_path: Path,
) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    corpus = load_retrieval_corpus(manifest.corpus_path)
    _, qa_service = _services()

    response = qa_service.answer(corpus=corpus, query="zebra invoice compliance")

    assert response.answer_mode == "low_evidence"
    assert response.answer_strategy == "grounded_low_evidence"
    assert response.citations == ()
    assert response.retrieval_hits


def test_answer_citation_formats_multi_page_labels() -> None:
    citation = AnswerCitation(
        document_id="d" * 64,
        unit_id="unit-001",
        page_span=PageSpan(start_page=0, end_page=2),
        page_label="1-3",
    )

    assert citation.page_label == "1-3"
    assert citation.page_span == PageSpan(start_page=0, end_page=2)
