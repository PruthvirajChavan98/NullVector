"""Synthetic retrieval artifact fixtures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from nullvector.domain import (
    AcquisitionManifest,
    AcquisitionRequest,
    AcquisitionRunManifest,
    AcquisitionSettings,
    AnchorSource,
    BoundingBox,
    CanonicalDocumentLedger,
    CanonicalPage,
    DocumentFingerprint,
    ExtractionProvenance,
    GroundingEvidence,
    HierarchyNode,
    LineBlock,
    NodeAnchor,
    NodeCard,
    NodeOwnedSpan,
    NodeSummary,
    NodeSummaryMethod,
    OutlineSource,
    PageSourceAnchor,
    PageSpan,
    SourceDocumentKind,
    SourceMetadata,
    SourceTrack,
    StructuredRegionInsight,
    TableArtifact,
    TreeBuildManifest,
    TreeBuildRequest,
    TreeNodeVerificationResult,
    TreeSettings,
    UnassignedPageSpan,
    VerificationReport,
    VisualArtifact,
    VisualEnrichmentAttachment,
)
from nullvector.domain.common import ContentSpan
from nullvector.domain.events import ContentAuthoritativeness
from nullvector.domain.tree import HierarchyOrigin, VerificationStatus
from nullvector.ingest.acquisition_service import AcquisitionService
from nullvector.ingest.projection import build_canonical_text_substrate
from nullvector.retrieval import RetrievalCorpusBuilder
from nullvector.storage._serialization import (
    canonical_json_bytes,
)
from nullvector.storage._serialization import (
    settings_digest as acquisition_settings_digest,
)
from nullvector.tree import build_tree


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )


def _native_provenance(
    *,
    authoritativeness: ContentAuthoritativeness,
) -> ExtractionProvenance:
    return ExtractionProvenance(
        source_track=SourceTrack.NATIVE,
        producer_name="synthetic-retrieval-fixture",
        grounded_in_native_metadata=True,
        grounded_in_bbox=True,
        content_authoritativeness=authoritativeness,
    )


def _line_block(*, page_index: int, reading_index: int, text: str) -> LineBlock:
    return LineBlock(
        line_id=f"page-{page_index}-line-{reading_index:04d}",
        bbox=BoundingBox(
            x0=0.0,
            y0=float(reading_index * 14),
            x1=float(max(len(text), 1) * 7),
            y1=float(reading_index * 14 + 12),
        ),
        content=text,
        reading_index=reading_index,
        occurrence_index=0,
        top_y=float(reading_index * 14),
        font_size=12.0,
        provenance=_native_provenance(
            authoritativeness=ContentAuthoritativeness.AUTHORITATIVE,
        ),
    )


@dataclass(frozen=True)
class SyntheticRetrievalBundle:
    """Paths and expected values for synthetic retrieval tests."""

    acquisition_manifest_path: Path
    tree_manifest_path: Path
    cached_attachment: VisualEnrichmentAttachment
    expected_node_text: str
    document_id: str


def write_synthetic_bundle(
    tmp_path: Path,
    *,
    document_id: str | None = None,
    bundle_name: str = "synthetic",
    section_title: str = "Appendix A",
    body_lines: tuple[str, ...] = ("Alpha body line", "Beta body line"),
    summary_text: str | None = None,
    keywords: tuple[str, ...] = ("appendix", "alpha"),
) -> SyntheticRetrievalBundle:
    """Create a synthetic acquisition + tree artifact bundle for retrieval tests."""

    document_id = document_id or ("a" * 64)
    acquisition_root = tmp_path / f"{bundle_name}-acquisition"
    tree_root = tmp_path / f"{bundle_name}-tree"
    source_path = acquisition_root / "source" / "original.pdf"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"%PDF-1.4 synthetic retrieval fixture")

    page_render = acquisition_root / "assets" / "pages" / "000000" / "render-144dpi.png"
    page_asset = acquisition_root / "assets" / "pages" / "000000" / "page-0-visual.png"
    page_render.parent.mkdir(parents=True, exist_ok=True)
    page_render.write_bytes(b"png-render")
    page_asset.write_bytes(b"png-crop")

    page_one_lines = (section_title, *body_lines)
    page_one_text = "\n".join(page_one_lines)
    alpha_start = page_one_text.index(body_lines[0])
    expected_node_text = page_one_text[alpha_start:]

    ledger = CanonicalDocumentLedger(
        document_id=document_id,
        source_fingerprint=DocumentFingerprint(
            document_id=document_id,
            source_path=str(source_path),
            sha256=document_id,
            file_size_bytes=source_path.stat().st_size,
            page_count=2,
        ),
        source_metadata=SourceMetadata(
            source_path=str(source_path),
            file_size_bytes=source_path.stat().st_size,
            mime_type="application/pdf",
            page_count=2,
        ),
        acquisition_manifest=AcquisitionManifest(
            source_fingerprint_sha256=document_id,
            settings_digest=acquisition_settings_digest(AcquisitionSettings()),
            acquisition_provider_identity=f"{bundle_name}-retrieval-fixture",
            selected_outline_source=OutlineSource.NONE,
            ledger_artifact_path=str(
                acquisition_root / "ledger" / "canonical-document-ledger.json"
            ),
        ),
        pages=(
            CanonicalPage(
                page_index=0,
                width=612.0,
                height=792.0,
                native_available=False,
                blocks=(
                    VisualArtifact(
                        visual_id="page-0-visual-0000",
                        bbox=BoundingBox(x0=10.0, y0=10.0, x1=120.0, y1=140.0),
                        reading_index=0,
                        kind_hint="cover_figure",
                        image_ref="page-0-image-0000",
                        asset_path=str(page_asset),
                        page_render_path=str(page_render),
                        render_dpi=144,
                        needs_enrichment=True,
                        provenance=_native_provenance(
                            authoritativeness=ContentAuthoritativeness.SUPPLEMENTAL,
                        ),
                    ),
                ),
                events=(),
            ),
            CanonicalPage(
                page_index=1,
                width=612.0,
                height=792.0,
                native_available=True,
                blocks=(
                    _line_block(page_index=1, reading_index=0, text=page_one_lines[0]),
                    _line_block(page_index=1, reading_index=1, text=page_one_lines[1]),
                    _line_block(page_index=1, reading_index=2, text=page_one_lines[2]),
                    TableArtifact(
                        table_id="page-1-table-0000",
                        bbox=BoundingBox(x0=20.0, y0=200.0, x1=200.0, y1=260.0),
                        reading_index=3,
                        rows=(("Name", "Value"), ("Alpha", "1"), ("Beta", "2")),
                        markdown_projection="| Name | Value |\n| Alpha | 1 |\n| Beta | 2 |",
                        provenance=_native_provenance(
                            authoritativeness=ContentAuthoritativeness.SUPPLEMENTAL,
                        ),
                        grounding=GroundingEvidence(
                            has_native_text_anchor=True,
                            has_page_bbox_anchor=True,
                            has_layout_anchor=True,
                        ),
                    ),
                ),
                events=(),
            ),
        ),
        document_events=(),
    )
    substrate = build_canonical_text_substrate(ledger)
    ledger_path = acquisition_root / "ledger" / "canonical-document-ledger.json"
    substrate_path = acquisition_root / "projection" / "canonical-text-substrate.json"
    outline_path = acquisition_root / "outline" / "selected.json"
    events_path = acquisition_root / "events" / "document-events.jsonl"
    _write_json(ledger_path, ledger)
    _write_json(substrate_path, substrate)
    _write_json(outline_path, {"selected_source": "none", "entries": []})
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text("", encoding="utf-8")

    acquisition_manifest = AcquisitionRunManifest(
        acquisition_run_id="synthetic-acquisition-run",
        document_id=document_id,
        artifact_root=str(acquisition_root),
        source_fingerprint=ledger.source_fingerprint,
        settings=AcquisitionSettings(),
        settings_digest=acquisition_settings_digest(AcquisitionSettings()),
        provider_identity=f"{bundle_name}-retrieval-fixture",
        ledger_path=str(ledger_path),
        source_copy_path=str(source_path),
        event_stream_path=str(events_path),
        selected_outline_source=OutlineSource.NONE,
        outline_quality_reports=(),
        selected_outline_path=str(outline_path),
        pymupdf_outline_path=str(outline_path),
        pymupdf_rich_outline_path=str(outline_path),
        pypdf_outline_path=str(outline_path),
        page_count=2,
        canonical_text_substrate_path=str(substrate_path),
    )
    acquisition_manifest_path = acquisition_root / "manifest.json"
    _write_json(acquisition_manifest_path, acquisition_manifest)

    node_id = (
        "node-appendix-a"
        if bundle_name == "synthetic" and section_title == "Appendix A"
        else f"node-{bundle_name}"
    )
    node = HierarchyNode(
        node_id=node_id,
        document_id=document_id,
        path=(section_title,),
        level=1,
        title=section_title,
        normalized_title=section_title.casefold(),
        page_span=PageSpan(start_page=1, end_page=1),
        heading_anchor=NodeAnchor(
            page=1,
            start_offset=0,
            end_offset=len(section_title),
            anchor_text=section_title,
            anchor_source=AnchorSource.TEXT,
            occurrence_index=0,
        ),
        owned_spans=(
            NodeOwnedSpan(
                kind="body",
                span=ContentSpan(
                    start_page=1,
                    start_offset=alpha_start,
                    end_page=1,
                    end_offset=len(page_one_text),
                ),
            ),
        ),
        source_anchors=(
            PageSourceAnchor(
                page=1,
                start_offset=alpha_start,
                end_offset=alpha_start + len(body_lines[0]),
                quote=body_lines[0],
            ),
        ),
        origin=HierarchyOrigin.INFERRED,
        confidence=1.0,
    )
    node_card = NodeCard(
        node_id=node.node_id,
        document_id=document_id,
        path=node.path,
        level=node.level,
        title=node.title,
        page_span=node.page_span,
        owned_spans=node.owned_spans,
        source_anchors=node.source_anchors,
    )
    node_summary = NodeSummary(
        node_id=node.node_id,
        summary=summary_text
        or f"{section_title} summarizes {' and '.join(line.casefold() for line in body_lines)}.",
        keywords=keywords,
        summary_method=NodeSummaryMethod.PASSTHROUGH,
        token_count=10,
        estimated_token_count=10,
        exact_token_count=10,
        tokenizer_identity="synthetic-tokenizer",
    )
    unassigned_span = UnassignedPageSpan(
        document_id=document_id,
        reason="before_first_heading",
        page_span=PageSpan(start_page=0, end_page=0),
    )
    verification_report = VerificationReport(
        document_id=document_id,
        tree_run_id="synthetic-tree-run",
        status=VerificationStatus.FAILED,
        node_results=(
            TreeNodeVerificationResult(
                document_id=document_id,
                tree_run_id="synthetic-tree-run",
                subject_id=node.node_id,
                status=VerificationStatus.PASSED,
                issues=(),
                covered_page_span=node.page_span,
            ),
        ),
        unassigned_spans=(unassigned_span,),
    )

    tree_settings = TreeSettings()
    tree_digest = hashlib.sha256(canonical_json_bytes(tree_settings)).hexdigest()
    placeholder_json_files: dict[Path, object] = {
        tree_root / "strategy" / "attempts" / "01" / "headings.json": {},
        tree_root / "strategy" / "attempts" / "01" / "raw-hierarchy.json": [],
        tree_root / "strategy" / "attempts" / "01" / "repair-requests.json": [],
        tree_root / "strategy" / "attempts" / "01" / "repair-decisions.json": [],
        tree_root / "strategy" / "attempts" / "01" / "repaired-hierarchy.json": [],
        tree_root / "strategy" / "attempts" / "01" / "build-report.json": {},
        tree_root / "run-index.json": {},
    }
    for path, payload in placeholder_json_files.items():
        _write_json(path, payload)

    committed_path = tree_root / "strategy" / "attempts" / "01" / "committed.json"
    node_cards_path = tree_root / "strategy" / "attempts" / "01" / "node-cards.json"
    node_summaries_path = tree_root / "strategy" / "attempts" / "01" / "node-summaries.json"
    unassigned_path = tree_root / "strategy" / "attempts" / "01" / "unassigned-spans.json"
    verification_path = tree_root / "strategy" / "attempts" / "01" / "verification-report.json"
    _write_json(committed_path, (node,))
    _write_json(node_cards_path, (node_card,))
    _write_json(node_summaries_path, (node_summary,))
    _write_json(unassigned_path, (unassigned_span,))
    _write_json(verification_path, verification_report)

    tree_manifest = TreeBuildManifest(
        tree_run_id="synthetic-tree-run",
        document_id=document_id,
        registry_root=str(tree_root / "_registry"),
        acquisition_manifest_path=str(acquisition_manifest_path),
        acquisition_artifact_identity=str(acquisition_manifest_path),
        acquisition_fingerprint_sha256=document_id,
        artifact_root=str(tree_root),
        settings=tree_settings,
        settings_digest=tree_digest,
        run_index_path=str(tree_root / "run-index.json"),
        headings_path=str(next(iter(placeholder_json_files.keys()))),
        raw_hierarchy_path=str(tree_root / "strategy" / "attempts" / "01" / "raw-hierarchy.json"),
        repair_requests_path=str(
            tree_root / "strategy" / "attempts" / "01" / "repair-requests.json"
        ),
        repair_decisions_path=str(
            tree_root / "strategy" / "attempts" / "01" / "repair-decisions.json"
        ),
        repaired_hierarchy_path=str(
            tree_root / "strategy" / "attempts" / "01" / "repaired-hierarchy.json"
        ),
        committed_hierarchy_path=str(committed_path),
        node_cards_path=str(node_cards_path),
        unassigned_spans_path=str(unassigned_path),
        verification_report_path=str(verification_path),
        build_report_path=str(tree_root / "strategy" / "attempts" / "01" / "build-report.json"),
        node_summaries_path=str(node_summaries_path),
        committed_node_count=1,
        unassigned_span_count=1,
    )
    tree_manifest_path = tree_root / "manifest.json"
    _write_json(tree_manifest_path, tree_manifest)

    cached_attachment = VisualEnrichmentAttachment(
        attachment_id=f"attach-{bundle_name}-page-0-visual",
        document_id=document_id,
        region_id="page-0-visual-0000",
        provider_identity=f"cached-{bundle_name}-fixture",
        authoritative=False,
        insight=StructuredRegionInsight(
            summary="A title-page illustration of a pipeline overview.",
            labels=("illustration",),
            attributes={"kind": "overview"},
            confidence=0.9,
        ),
        audit_path=str(tmp_path / f"cached-{bundle_name}-attachment-audit.json"),
    )

    return SyntheticRetrievalBundle(
        acquisition_manifest_path=acquisition_manifest_path,
        tree_manifest_path=tree_manifest_path,
        cached_attachment=cached_attachment,
        expected_node_text=expected_node_text,
        document_id=document_id,
    )


def build_markdown_tree_search_artifacts(
    tmp_path: Path,
    *,
    bundle_name: str,
    lines: tuple[str, ...],
) -> tuple[Path, Path]:
    """Build persisted markdown-backed tree and retrieval artifacts for retrieval tests."""

    source_path = tmp_path / f"{bundle_name}.md"
    source_path.write_text("\n".join(lines), encoding="utf-8")

    acquisition_manifest = AcquisitionService().acquire(
        AcquisitionRequest(
            source_path=str(source_path),
            acquisition_run_id=f"{bundle_name}-acquire",
            artifact_root=str(tmp_path / f"{bundle_name}-acquisition"),
            source_kind=SourceDocumentKind.MARKDOWN,
            provider_identity="markdown_native",
        )
    )
    if acquisition_manifest.artifact_root is None:
        pytest.fail("expected acquisition artifact_root for markdown tree-search fixture")
    acquisition_manifest_path = Path(acquisition_manifest.artifact_root) / "manifest.json"
    tree_manifest = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(acquisition_manifest_path),
            tree_run_id=f"{bundle_name}-tree",
            summarize=False,
        )
    )
    if tree_manifest.artifact_root is None:
        pytest.fail("expected tree artifact_root for markdown tree-search fixture")
    tree_manifest_path = Path(tree_manifest.artifact_root) / "manifest.json"
    retrieval_manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(acquisition_manifest_path),
        tree_manifest_path=str(tree_manifest_path),
    )
    if retrieval_manifest.artifact_root is None:
        pytest.fail("expected retrieval artifact_root for markdown tree-search fixture")
    retrieval_manifest_path = Path(retrieval_manifest.artifact_root) / "manifest.json"
    return (tree_manifest_path, retrieval_manifest_path)
