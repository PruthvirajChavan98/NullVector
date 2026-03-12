"""Unit tests for authoritative domain contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from strataforge.constants import EXPECTED_PYMUPDF_VERSION, EXPECTED_PYPDF_VERSION
from strataforge.domain import (
    AcquisitionManifest,
    AcquisitionRequest,
    AcquisitionRunIndex,
    AcquisitionRunManifest,
    AcquisitionSettings,
    AnchorSource,
    BoundingBox,
    CanonicalDocumentLedger,
    CanonicalPage,
    ContentAuthoritativeness,
    ContentSpan,
    DecompositionMethod,
    DecompositionReport,
    DocumentEvent,
    DocumentFingerprint,
    EventSeverity,
    ExtractionProvenance,
    GroundingEvidence,
    HeadingCandidate,
    HeadingScoreBreakdown,
    HeadingSourceKind,
    HierarchyNode,
    HierarchyOrigin,
    LineBlock,
    NodeAnchor,
    NodeCard,
    NodeOwnedSpan,
    OcrMode,
    OutlineEntry,
    PageEvent,
    PageLedgerRow,
    PageSourceAnchor,
    PageSpan,
    ParseJobLifecycle,
    ParseJobState,
    ParseRequest,
    ParserSettings,
    RepairDecision,
    RepairStatus,
    SourceMetadata,
    SourceTrack,
    SynthesisLine,
    SynthesisPage,
    SynthesisTextProjection,
    SynthesisTrustSummary,
    SynthesisUnresolvedRegion,
    TableArtifact,
    TextBlock,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeNodeVerificationResult,
    TreeRunIndex,
    TreeSettings,
    TreeSynthesisView,
    TrustTier,
    UnassignedPageSpan,
    UnresolvedRegion,
    VerificationIssue,
    VerificationReport,
    VerificationResult,
    VisualArtifact,
)
from strataforge.domain.models import (
    OutlineSource,
    PageExtractionMethod,
    VerificationSeverity,
    VerificationStatus,
)

SHA256 = "a" * 64
TEXT_SHA256 = "b" * 64


def make_anchor() -> PageSourceAnchor:
    return PageSourceAnchor(page=4, start_offset=10, end_offset=18, quote="Section heading")


def make_provenance() -> ExtractionProvenance:
    return ExtractionProvenance(
        source_track=SourceTrack.NATIVE,
        producer_name="pymupdf",
        producer_version=EXPECTED_PYMUPDF_VERSION,
        confidence=0.99,
        grounded_in_native_metadata=True,
        grounded_in_bbox=True,
        content_authoritativeness=ContentAuthoritativeness.AUTHORITATIVE,
    )


def make_grounding() -> GroundingEvidence:
    return GroundingEvidence(
        has_native_text_anchor=True,
        has_page_bbox_anchor=True,
        has_layout_anchor=True,
        supporting_native_refs=("page-0001:line-0003",),
    )


def test_page_span_rejects_inverted_bounds() -> None:
    with pytest.raises(ValidationError):
        PageSpan(start_page=7, end_page=6)


def test_content_span_rejects_same_page_inverted_offsets() -> None:
    with pytest.raises(ValidationError):
        ContentSpan(
            start_page=1,
            start_offset=12,
            end_page=1,
            end_offset=10,
        )


def test_bounding_box_rejects_inverted_bounds() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(x0=12.0, y0=20.0, x1=10.0, y1=25.0)


def test_page_ledger_row_requires_consistent_offsets() -> None:
    with pytest.raises(ValidationError):
        PageLedgerRow(
            document_id="doc-001",
            parse_run_id="run-001",
            source_path="fixtures/pdfs/sample.pdf",
            page_index=0,
            extraction_method=PageExtractionMethod.NATIVE_TEXT,
            text_offset_start=0,
            text_offset_end=20,
            text_length=12,
            text_sha256=SHA256,
            text_artifact_path="artifacts/run-001/page-0000.txt",
            native_text_artifact_path="artifacts/run-001/page-0000.native.txt",
        )


def test_node_card_requires_anchor_for_summary() -> None:
    with pytest.raises(ValidationError):
        NodeCard(
            node_id="node-001",
            document_id="doc-001",
            path=("Root", "Section 1"),
            level=2,
            title="Section 1",
            page_span=PageSpan(start_page=0, end_page=2),
            summary="A bounded summary.",
        )


def test_parse_job_state_requires_error_message_for_failed_lifecycle() -> None:
    with pytest.raises(ValidationError):
        ParseJobState(
            job_id="job-001",
            document_id="doc-001",
            parse_run_id="run-001",
            lifecycle=ParseJobLifecycle.FAILED,
            current_step="verify-tree",
        )


def test_parse_job_state_rejects_error_message_for_non_failed_lifecycle() -> None:
    with pytest.raises(ValidationError):
        ParseJobState(
            job_id="job-001",
            document_id="doc-001",
            parse_run_id="run-001",
            lifecycle=ParseJobLifecycle.RUNNING,
            current_step="verify-tree",
            error_message="not allowed yet",
        )


def test_verification_result_rejects_passed_status_with_error_issue() -> None:
    issue = VerificationIssue(
        code="missing-title",
        message="Expected heading was not found.",
        severity=VerificationSeverity.ERROR,
        page_span=PageSpan(start_page=3, end_page=4),
    )

    with pytest.raises(ValidationError):
        VerificationResult(
            document_id="doc-001",
            parse_run_id="run-001",
            subject_id="node-001",
            status=VerificationStatus.PASSED,
            issues=(issue,),
        )


def test_page_span_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PageSpan(start_page=1, end_page=2, extra_field=3)  # type: ignore[call-arg]


def test_parse_request_rejects_coerced_types_under_strict_mode() -> None:
    with pytest.raises(ValidationError):
        ParseRequest.model_validate(
            {
                "source_path": "fixtures/pdfs/sample.pdf",
                "parse_run_id": "run-001",
                "settings": {
                    "ocr_languages": ("eng",),
                    "ocr_dpi": "300",
                    "tessdata_path": "/tmp/tessdata",
                    "pymupdf_version": EXPECTED_PYMUPDF_VERSION,
                    "pypdf_version": EXPECTED_PYPDF_VERSION,
                },
            },
        )


def test_acquisition_settings_reject_invalid_thresholds() -> None:
    with pytest.raises(ValidationError):
        AcquisitionSettings(image_region_warning_threshold=1.2)


def test_parse_job_state_model_is_immutable() -> None:
    job_state = ParseJobState(
        job_id="job-001",
        document_id="doc-001",
        parse_run_id="run-001",
        lifecycle=ParseJobLifecycle.RUNNING,
        current_step="extract-text",
    )

    with pytest.raises(ValidationError):
        job_state.retry_count = 2


def test_models_accept_valid_phase01_payloads() -> None:
    anchor = make_anchor()
    settings = ParserSettings(
        tessdata_path="/usr/share/tesseract-ocr/5/tessdata",
        pymupdf_version=EXPECTED_PYMUPDF_VERSION,
        pypdf_version=EXPECTED_PYPDF_VERSION,
    )
    node_card = NodeCard(
        node_id="node-001",
        document_id="doc-001",
        path=("Root", "Section 1"),
        level=2,
        title="Section 1",
        page_span=PageSpan(start_page=3, end_page=5),
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=3,
                    start_offset=0,
                    end_page=5,
                    end_offset=120,
                ),
            ),
        ),
        summary="Section 1 covers deterministic parsing.",
        keywords=("parsing", "deterministic"),
        source_anchors=(anchor,),
    )
    ledger_row = PageLedgerRow(
        document_id="doc-001",
        parse_run_id="run-001",
        source_path="fixtures/pdfs/sample.pdf",
        page_index=3,
        page_label="4",
        extraction_method=PageExtractionMethod.MIXED,
        needs_ocr=True,
        native_text_available=True,
        ocr_mode=OcrMode.PARTIAL,
        ocr_reason_codes=("low_text_density", "high_image_coverage"),
        text_offset_start=120,
        text_offset_end=210,
        text_length=90,
        text_sha256=SHA256,
        native_text_sha256=TEXT_SHA256,
        native_word_count=3,
        native_char_count=12,
        image_coverage_ratio=0.88,
        vector_path_count=12,
        dense_small_vector_count=0,
        render_artifact_path="artifacts/run-001/page-0003/render.png",
        text_artifact_path="artifacts/run-001/page-0003/ocr.txt",
        native_text_artifact_path="artifacts/run-001/page-0003/native.txt",
        native_rawdict_artifact_path="artifacts/run-001/page-0003/native.rawdict.json.gz",
        ocr_text_artifact_path="artifacts/run-001/page-0003/ocr.txt",
        ocr_rawdict_artifact_path="artifacts/run-001/page-0003/ocr.rawdict.json.gz",
        ocr_render_artifact_path="artifacts/run-001/page-0003/render.png",
    )
    verification_result = VerificationResult(
        document_id="doc-001",
        parse_run_id="run-001",
        subject_id="node-001",
        status=VerificationStatus.PASSED,
        covered_page_span=node_card.page_span,
    )
    parse_request = ParseRequest(
        source_path="fixtures/pdfs/phase01/born_digital_with_outline.pdf",
        parse_run_id="run-001",
        settings=settings,
    )

    assert node_card.source_anchors == (anchor,)
    assert ledger_row.text_length == 90
    assert ledger_row.ocr_mode is OcrMode.PARTIAL
    assert verification_result.status is VerificationStatus.PASSED
    assert parse_request.settings.pymupdf_version == EXPECTED_PYMUPDF_VERSION
    assert OutlineSource.PYMUPDF.value == "pymupdf"


def test_acquisition_request_requires_exactly_valid_payloads() -> None:
    request = AcquisitionRequest(
        source_path="fixtures/pdfs/phase01/born_digital_with_outline.pdf",
        acquisition_run_id="acq-run-001",
        provider_identity="native_pymupdf",
        settings=AcquisitionSettings(),
    )

    assert request.provider_identity == "native_pymupdf"
    assert request.artifact_root == "artifacts/acquisition_runs"


def test_canonical_document_ledger_accepts_v2_payloads() -> None:
    fingerprint = DocumentFingerprint(
        document_id=SHA256,
        source_path="/tmp/spec.pdf",
        sha256=SHA256,
        file_size_bytes=1024,
        page_count=1,
    )
    source_metadata = SourceMetadata(
        source_path="/tmp/spec.pdf",
        file_size_bytes=1024,
        mime_type="application/pdf",
        page_count=1,
    )
    acquisition_manifest = AcquisitionManifest(
        source_fingerprint_sha256=SHA256,
        settings_digest=TEXT_SHA256,
        acquisition_provider_identity="native_pymupdf",
        enrichment_providers=("custom_adapter",),
        selected_outline_source=OutlineSource.PYMUPDF,
        outline_quality_reports=(),
        selected_outline_entries=(
            OutlineEntry(
                level=1,
                title="Introduction",
                page_index=0,
                source=OutlineSource.PYMUPDF,
            ),
        ),
        ledger_artifact_path="artifacts/acquisition/ledger.json",
        outline_artifact_paths=("artifacts/acquisition/outline.json",),
        event_stream_path="artifacts/acquisition/events.jsonl",
    )
    bbox = BoundingBox(x0=0.0, y0=0.0, x1=200.0, y1=40.0)
    provenance = make_provenance()
    grounding = make_grounding()
    page = CanonicalPage(
        page_index=0,
        page_label="1",
        width=612.0,
        height=792.0,
        rotation=0.0,
        native_available=True,
        blocks=(
            TextBlock(
                block_id="text-001",
                bbox=bbox,
                content="1 Introduction",
                reading_index=0,
                line_count=1,
                word_count=2,
                provenance=provenance,
                grounding=grounding,
            ),
            LineBlock(
                line_id="line-001",
                bbox=bbox,
                content="1 Introduction",
                reading_index=0,
                occurrence_index=0,
                top_y=10.0,
                font_size=16.0,
                font_family_hint="Helvetica-Bold",
                provenance=provenance,
            ),
            TableArtifact(
                table_id="table-001",
                bbox=BoundingBox(x0=0.0, y0=60.0, x1=200.0, y1=120.0),
                reading_index=1,
                rows=(("Col A", "Col B"), ("1", "2")),
                markdown_projection="| Col A | Col B |",
                provenance=provenance,
                grounding=grounding,
            ),
            VisualArtifact(
                visual_id="visual-001",
                bbox=BoundingBox(x0=0.0, y0=130.0, x1=200.0, y1=260.0),
                reading_index=2,
                kind_hint="chart",
                image_ref="pages/000000/figure.png",
                needs_enrichment=True,
                provenance=provenance.model_copy(
                    update={
                        "source_track": SourceTrack.VISUAL_ENRICHMENT,
                        "content_authoritativeness": ContentAuthoritativeness.INTERPRETIVE,
                    }
                ),
            ),
            UnresolvedRegion(
                region_id="region-001",
                bbox=BoundingBox(x0=0.0, y0=270.0, x1=200.0, y1=320.0),
                reason_code="LOW_TEXT_DENSITY_HIGH_IMAGE_COVERAGE",
                severity=EventSeverity.WARNING,
                recommended_fallback="external_ocr",
                reading_index=3,
                provenance=provenance,
            ),
        ),
        events=(
            PageEvent(
                event_id="page-event-001",
                event_name="PageNativeParsed",
                page_index=0,
                severity=EventSeverity.INFO,
                message="Page parsed through native acquisition",
            ),
        ),
    )
    ledger = CanonicalDocumentLedger(
        document_id=fingerprint.document_id,
        source_fingerprint=fingerprint,
        source_metadata=source_metadata,
        acquisition_manifest=acquisition_manifest,
        pages=(page,),
        document_events=(
            DocumentEvent(
                event_id="doc-event-001",
                event_name="AcquisitionStarted",
                severity=EventSeverity.INFO,
                message="Acquisition began for the document",
            ),
        ),
    )

    assert ledger.pages[0].blocks[0].block_type == "text_block"
    assert ledger.pages[0].blocks[-1].block_type == "unresolved_region"
    assert ledger.acquisition_manifest.acquisition_provider_identity == "native_pymupdf"


def test_tree_synthesis_view_accepts_projection_payloads() -> None:
    synthesis_line = SynthesisLine(
        line_id="line-001",
        content="1 Introduction",
        normalized_text="1 introduction",
        casefold_punct_text="1 introduction",
        page_index=0,
        reading_index=0,
        start_offset=0,
        end_offset=14,
        occurrence_index=0,
        bbox=BoundingBox(x0=0.0, y0=0.0, x1=200.0, y1=18.0),
        top_y=10.0,
        font_size=16.0,
        layout_cues_available=True,
        trust_tier=TrustTier.NATIVE_LAYOUT_BACKED,
    )
    synthesis_page = SynthesisPage(
        page_index=0,
        page_label="1",
        width=612.0,
        height=792.0,
        lines=(synthesis_line,),
        table_text_projections=(
            SynthesisTextProjection(
                projection_id="table-proj-001",
                content="Table 1: Deterministic values",
                reading_index=1,
                bbox=BoundingBox(x0=0.0, y0=60.0, x1=200.0, y1=120.0),
                trust_tier=TrustTier.NATIVE_EXACT,
            ),
        ),
        trust_summary=SynthesisTrustSummary(
            dominant_trust_tier=TrustTier.NATIVE_LAYOUT_BACKED,
            line_count_by_trust_tier={
                TrustTier.NATIVE_LAYOUT_BACKED: 1,
            },
        ),
        unresolved_regions=(
            SynthesisUnresolvedRegion(
                region_id="region-001",
                bbox=BoundingBox(x0=0.0, y0=270.0, x1=200.0, y1=320.0),
                reason_code="POSSIBLE_SCANNED_TABLE",
                severity=EventSeverity.WARNING,
                recommended_fallback="external_ocr",
            ),
        ),
    )
    projection = TreeSynthesisView(
        document_id="doc-001",
        pages=(synthesis_page,),
        outline_entries=(
            OutlineEntry(
                level=1,
                title="Introduction",
                page_index=0,
                source=OutlineSource.PYMUPDF,
            ),
        ),
        projection_events=(
            DocumentEvent(
                event_id="proj-event-001",
                event_name="ProjectionCreated",
                severity=EventSeverity.INFO,
                message="Projection generated from the canonical ledger",
            ),
        ),
    )

    assert projection.pages[0].lines[0].trust_tier is TrustTier.NATIVE_LAYOUT_BACKED
    assert projection.pages[0].trust_summary.dominant_trust_tier is TrustTier.NATIVE_LAYOUT_BACKED


def test_tree_settings_reject_invalid_threshold_order() -> None:
    with pytest.raises(ValidationError):
        TreeSettings(
            outline_high_agreement_threshold=0.2,
            outline_low_agreement_threshold=0.4,
        )


def test_models_accept_valid_phase02_payloads() -> None:
    heading_anchor = NodeAnchor(
        page=1,
        start_offset=0,
        end_offset=8,
        anchor_text="Overview",
        anchor_source=AnchorSource.TEXT,
        occurrence_index=0,
    )
    heading_candidate = HeadingCandidate(
        document_id="c" * 64,
        page_index=1,
        title="Overview",
        normalized_title="overview",
        anchor=heading_anchor,
        source_kind=HeadingSourceKind.OUTLINE,
        level_hint=1,
        outline_level_hint=1,
        score_breakdown=HeadingScoreBreakdown(
            toc_overlap_signal=40,
            final_score=100,
        ),
        keep=True,
        high_confidence=True,
    )
    hierarchy_node = HierarchyNode(
        node_id="d" * 64,
        document_id="c" * 64,
        path=("Overview",),
        level=1,
        title="Overview",
        normalized_title="overview",
        page_span=PageSpan(start_page=1, end_page=1),
        heading_anchor=heading_anchor,
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=1,
                    start_offset=0,
                    end_page=1,
                    end_offset=8,
                ),
            ),
        ),
        source_anchors=(make_anchor(),),
        origin=HierarchyOrigin.OUTLINE,
        confidence=1.0,
    )
    verification_report = VerificationReport(
        document_id="c" * 64,
        tree_run_id="tree-run-001",
        status=VerificationStatus.PASSED,
        node_results=(
            TreeNodeVerificationResult(
                document_id="c" * 64,
                tree_run_id="tree-run-001",
                subject_id="d" * 64,
                status=VerificationStatus.PASSED,
                covered_page_span=PageSpan(start_page=1, end_page=1),
            ),
        ),
    )
    tree_request = TreeBuildRequest(
        acquisition_manifest_path="fixtures/phase02/inputs/clean_outline/manifest.json",
        tree_run_id="tree-run-001",
    )
    tree_index = TreeRunIndex(
        tree_run_id="tree-run-001",
        document_id="c" * 64,
        registry_root="/tmp/_tree_runs",
        acquisition_manifest_path="/tmp/manifest.json",
        acquisition_artifact_identity="/tmp/manifest.json",
        acquisition_fingerprint_sha256="e" * 64,
        settings_digest="f" * 64,
        manifest_path="/tmp/doc/tree/tree-run-001/manifest.json",
    )
    tree_manifest = TreeBuildManifest(
        tree_run_id="tree-run-001",
        document_id="c" * 64,
        registry_root="/tmp/_tree_runs",
        acquisition_manifest_path="/tmp/manifest.json",
        acquisition_artifact_identity="/tmp/manifest.json",
        acquisition_fingerprint_sha256="e" * 64,
        artifact_root="/tmp/tree",
        settings=TreeSettings(),
        settings_digest="f" * 64,
        run_index_path="/tmp/_tree_runs/tree-run-001/run-index.json",
        headings_path="/tmp/tree/headings/candidates.json",
        raw_hierarchy_path="/tmp/tree/hierarchy/raw.json",
        repair_requests_path="/tmp/tree/repair/requests.json",
        repair_decisions_path="/tmp/tree/repair/decisions.json",
        repaired_hierarchy_path="/tmp/tree/hierarchy/repaired.json",
        committed_hierarchy_path="/tmp/tree/hierarchy/committed.json",
        node_cards_path="/tmp/tree/hierarchy/node-cards.json",
        unassigned_spans_path="/tmp/tree/unassigned-spans.json",
        verification_report_path="/tmp/tree/verify/report.json",
        build_report_path="/tmp/tree/build-report.json",
        committed_node_count=1,
        unassigned_span_count=0,
    )
    repair_decision = RepairDecision(
        subject_id="d" * 64,
        status=RepairStatus.NOT_REQUESTED,
        message="no repair work was needed",
    )
    decomposition_report = DecompositionReport(
        decomposition_method=DecompositionMethod.NONE,
        empty_parent_count=0,
    )
    unassigned_span = UnassignedPageSpan(
        document_id="c" * 64,
        reason="before_first_heading",
        page_span=PageSpan(start_page=0, end_page=0),
    )

    assert heading_candidate.keep is True
    assert hierarchy_node.origin is HierarchyOrigin.OUTLINE
    assert hierarchy_node.owned_spans[0].span.end_offset == 8
    assert verification_report.status is VerificationStatus.PASSED
    assert tree_request.tree_run_id == "tree-run-001"
    assert tree_index.settings_digest == "f" * 64
    assert tree_index.acquisition_artifact_identity == "/tmp/manifest.json"
    assert tree_manifest.committed_node_count == 1
    assert tree_manifest.registry_root == "/tmp/_tree_runs"
    assert repair_decision.status is RepairStatus.NOT_REQUESTED
    assert decomposition_report.empty_parent_count == 0
    assert unassigned_span.page_span.start_page == 0


def test_tree_build_request_requires_acquisition_manifest_input() -> None:
    with pytest.raises(ValidationError):
        TreeBuildRequest.model_validate({"tree_run_id": "tree-run-001"})

    acquisition_request = TreeBuildRequest(
        acquisition_manifest_path="/tmp/acquisition-manifest.json",
        tree_run_id="tree-run-001",
    )

    assert acquisition_request.acquisition_manifest_path == "/tmp/acquisition-manifest.json"


def test_acquisition_run_contracts_accept_valid_payloads() -> None:
    settings = AcquisitionSettings()
    run_index = AcquisitionRunIndex(
        acquisition_run_id="acq-run-001",
        document_id=SHA256,
        source_fingerprint_sha256=SHA256,
        settings_digest=TEXT_SHA256,
        manifest_path="/tmp/acquisition/manifest.json",
    )
    run_manifest = AcquisitionRunManifest(
        acquisition_run_id="acq-run-001",
        document_id=SHA256,
        artifact_root="/tmp/acquisition",
        source_fingerprint=DocumentFingerprint(
            document_id=SHA256,
            source_path="/tmp/spec.pdf",
            sha256=SHA256,
            file_size_bytes=1024,
            page_count=1,
        ),
        settings=settings,
        settings_digest=TEXT_SHA256,
        provider_identity="native_pymupdf",
        ledger_path="/tmp/acquisition/ledger/canonical-document-ledger.json",
        source_copy_path="/tmp/acquisition/source/original.pdf",
        event_stream_path="/tmp/acquisition/events/document-events.jsonl",
        selected_outline_source=OutlineSource.PYMUPDF,
        outline_quality_reports=(),
        selected_outline_path="/tmp/acquisition/outline/selected.json",
        pymupdf_outline_path="/tmp/acquisition/outline/pymupdf.normalized.json",
        pymupdf_rich_outline_path="/tmp/acquisition/outline/pymupdf.rich.json",
        pypdf_outline_path="/tmp/acquisition/outline/pypdf.normalized.json",
        page_count=1,
        projection_view_path="/tmp/acquisition/projection/tree-synthesis-view.json",
    )

    assert run_index.acquisition_run_id == "acq-run-001"
    assert (
        run_manifest.projection_view_path == "/tmp/acquisition/projection/tree-synthesis-view.json"
    )
