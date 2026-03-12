"""Unit tests for authoritative domain contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from strataforge.constants import EXPECTED_PYMUPDF_VERSION, EXPECTED_PYPDF_VERSION
from strataforge.domain import (
    AnchorSource,
    ContentSpan,
    DecompositionMethod,
    DecompositionReport,
    HeadingCandidate,
    HeadingScoreBreakdown,
    HeadingSourceKind,
    HierarchyNode,
    HierarchyOrigin,
    NodeAnchor,
    NodeCard,
    NodeOwnedSpan,
    OcrMode,
    PageLedgerRow,
    PageSourceAnchor,
    PageSpan,
    ParseJobLifecycle,
    ParseJobState,
    ParseRequest,
    ParserSettings,
    RepairDecision,
    RepairStatus,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeNodeVerificationResult,
    TreeRunIndex,
    TreeSettings,
    UnassignedPageSpan,
    VerificationIssue,
    VerificationReport,
    VerificationResult,
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
        parse_manifest_path="fixtures/phase02/inputs/clean_outline/manifest.json",
        tree_run_id="tree-run-001",
    )
    tree_index = TreeRunIndex(
        tree_run_id="tree-run-001",
        document_id="c" * 64,
        registry_root="/tmp/_tree_runs",
        parse_manifest_path="/tmp/manifest.json",
        parse_artifact_identity="/tmp/manifest.json",
        parse_fingerprint_sha256="e" * 64,
        settings_digest="f" * 64,
        manifest_path="/tmp/doc/tree/tree-run-001/manifest.json",
    )
    tree_manifest = TreeBuildManifest(
        tree_run_id="tree-run-001",
        document_id="c" * 64,
        registry_root="/tmp/_tree_runs",
        parse_manifest_path="/tmp/manifest.json",
        parse_artifact_identity="/tmp/manifest.json",
        parse_fingerprint_sha256="e" * 64,
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
    assert tree_index.parse_artifact_identity == "/tmp/manifest.json"
    assert tree_manifest.committed_node_count == 1
    assert tree_manifest.registry_root == "/tmp/_tree_runs"
    assert repair_decision.status is RepairStatus.NOT_REQUESTED
    assert decomposition_report.empty_parent_count == 0
    assert unassigned_span.page_span.start_page == 0
