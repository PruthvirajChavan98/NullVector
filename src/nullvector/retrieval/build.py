"""Build retrieval corpora from acquisition and tree artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from nullvector.domain.common import PageSourceAnchor
from nullvector.domain.events import ContentAuthoritativeness, SourceTrack, TrustTier
from nullvector.domain.ledger import (
    CanonicalDocumentLedger,
    CanonicalTextPage,
    CanonicalTextSubstrate,
    TableArtifact,
    UnresolvedRegion,
    VisualArtifact,
)
from nullvector.domain.models import AcquisitionRunManifest, ContentSpan, PageSpan
from nullvector.domain.retrieval import (
    RetrievalCorpus,
    RetrievalEvidence,
    RetrievalManifest,
    RetrievalModality,
    RetrievalUnitType,
)
from nullvector.domain.tree import (
    HierarchyNode,
    NodeCard,
    NodeSummary,
    TreeBuildManifest,
    UnassignedPageSpan,
    VerificationReport,
    VisualRegionReference,
)
from nullvector.runtime_validation import validate_canonical_text_substrate_contract


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    return str(path)


def _resolve_artifact_path(root: Path, stored_path: str) -> Path:
    path = Path(stored_path)
    if path.is_absolute():
        return path
    return root / path


def _unique_non_empty(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split()).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def _source_anchor_payloads(
    anchors: tuple[PageSourceAnchor, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(cast(dict[str, object], anchor.model_dump(mode="json")) for anchor in anchors)


def _trust_tier_for_source(
    *,
    source_track: SourceTrack,
    authoritativeness: ContentAuthoritativeness,
    confidence: float | None,
) -> TrustTier:
    if source_track is SourceTrack.NATIVE:
        if authoritativeness is ContentAuthoritativeness.AUTHORITATIVE:
            return TrustTier.NATIVE_EXACT
        return TrustTier.NATIVE_LAYOUT_BACKED
    if source_track is SourceTrack.EXTERNAL_OCR:
        if confidence is not None and confidence >= 0.9:
            return TrustTier.EXTERNAL_OCR_HIGH
        if confidence is not None and confidence >= 0.75:
            return TrustTier.EXTERNAL_OCR_MEDIUM
        return TrustTier.EXTERNAL_OCR_LOW
    return TrustTier.VISUAL_INTERPRETIVE


def _content_span_for_page(page: CanonicalTextPage) -> ContentSpan:
    return ContentSpan(
        start_page=page.page_index,
        start_offset=0,
        end_page=page.page_index,
        end_offset=len(page.text),
    )


def _merge_content_spans(spans: tuple[ContentSpan, ...]) -> ContentSpan | None:
    if not spans:
        return None
    ordered = sorted(
        spans,
        key=lambda span: (
            span.start_page,
            span.start_offset,
            span.end_page,
            span.end_offset,
        ),
    )
    first = ordered[0]
    last = ordered[-1]
    return ContentSpan(
        start_page=first.start_page,
        start_offset=first.start_offset,
        end_page=last.end_page,
        end_offset=last.end_offset,
    )


def _text_for_content_span(
    *,
    pages_by_index: dict[int, CanonicalTextPage],
    span: ContentSpan,
) -> str:
    parts: list[str] = []
    for page_index in range(span.start_page, span.end_page + 1):
        page = pages_by_index.get(page_index)
        if page is None:
            continue
        start_offset = 0
        end_offset = len(page.text)
        if page_index == span.start_page:
            start_offset = min(span.start_offset, len(page.text))
        if page_index == span.end_page:
            end_offset = min(span.end_offset, len(page.text))
        if start_offset >= end_offset:
            continue
        parts.append(page.text[start_offset:end_offset])
    return "\n".join(part for part in parts if part).strip()


def _text_for_page_span(
    *,
    pages_by_index: dict[int, CanonicalTextPage],
    page_span: PageSpan,
) -> str:
    parts = [
        pages_by_index[page_index].text
        for page_index in range(page_span.start_page, page_span.end_page + 1)
        if page_index in pages_by_index and pages_by_index[page_index].text
    ]
    return "\n".join(parts).strip()


def _default_retrieval_root(
    *,
    acquisition_manifest_path: Path,
    acquisition_manifest: AcquisitionRunManifest,
    tree_manifest: TreeBuildManifest | None,
) -> Path:
    retrieval_run_id = (
        tree_manifest.tree_run_id
        if tree_manifest is not None
        else acquisition_manifest.acquisition_run_id
    )
    return acquisition_manifest_path.parent / "retrieval" / retrieval_run_id


def _load_acquisition_manifest(path: Path) -> AcquisitionRunManifest:
    return AcquisitionRunManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _load_tree_manifest(path: Path | None) -> TreeBuildManifest | None:
    if path is None:
        return None
    return TreeBuildManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _load_ledger(
    acquisition_manifest_path: Path,
    acquisition_manifest: AcquisitionRunManifest,
) -> CanonicalDocumentLedger:
    ledger_path = _resolve_artifact_path(
        Path(acquisition_manifest.artifact_root),
        acquisition_manifest.ledger_path,
    )
    if not ledger_path.exists():
        ledger_path = _resolve_artifact_path(
            acquisition_manifest_path.parent,
            acquisition_manifest.ledger_path,
        )
    return CanonicalDocumentLedger.model_validate_json(ledger_path.read_text(encoding="utf-8"))


def _load_text_substrate(
    acquisition_manifest_path: Path,
    acquisition_manifest: AcquisitionRunManifest,
) -> CanonicalTextSubstrate:
    substrate_path = validate_canonical_text_substrate_contract(
        acquisition_root=acquisition_manifest_path.parent,
        manifest=acquisition_manifest,
    )
    return CanonicalTextSubstrate.model_validate_json(substrate_path.read_text(encoding="utf-8"))


def _load_committed_nodes(tree_manifest: TreeBuildManifest | None) -> tuple[HierarchyNode, ...]:
    if tree_manifest is None:
        return ()
    payload = cast(list[dict[str, Any]], _read_json(Path(tree_manifest.committed_hierarchy_path)))
    return tuple(HierarchyNode.model_validate_json(json.dumps(item)) for item in payload)


def _load_node_cards(tree_manifest: TreeBuildManifest | None) -> tuple[NodeCard, ...]:
    if tree_manifest is None:
        return ()
    payload = cast(list[dict[str, Any]], _read_json(Path(tree_manifest.node_cards_path)))
    return tuple(NodeCard.model_validate_json(json.dumps(item)) for item in payload)


def _load_node_summaries(tree_manifest: TreeBuildManifest | None) -> tuple[NodeSummary, ...]:
    if tree_manifest is None or tree_manifest.node_summaries_path is None:
        return ()
    payload = cast(list[dict[str, Any]], _read_json(Path(tree_manifest.node_summaries_path)))
    return tuple(NodeSummary.model_validate_json(json.dumps(item)) for item in payload)


def _load_verification_report(tree_manifest: TreeBuildManifest | None) -> VerificationReport | None:
    if tree_manifest is None:
        return None
    return VerificationReport.model_validate_json(
        Path(tree_manifest.verification_report_path).read_text(encoding="utf-8")
    )


def _load_unassigned_spans(
    tree_manifest: TreeBuildManifest | None,
) -> tuple[UnassignedPageSpan, ...]:
    if tree_manifest is None:
        return ()
    payload = cast(list[dict[str, Any]], _read_json(Path(tree_manifest.unassigned_spans_path)))
    return tuple(UnassignedPageSpan.model_validate_json(json.dumps(item)) for item in payload)


def _build_page_units(
    text_substrate: CanonicalTextSubstrate,
) -> tuple[RetrievalEvidence, ...]:
    units: list[RetrievalEvidence] = []
    for page in sorted(text_substrate.pages, key=lambda item: item.page_index):
        if not page.text.strip():
            continue
        page_label = page.page_label or str(page.page_index + 1)
        units.append(
            RetrievalEvidence(
                unit_id=f"page-text-{page.page_index:06d}",
                document_id=text_substrate.document_id,
                unit_type=RetrievalUnitType.PAGE_TEXT,
                modality=RetrievalModality.TEXT,
                page_span=PageSpan(start_page=page.page_index, end_page=page.page_index),
                content_span=_content_span_for_page(page),
                title=f"Page {page_label}",
                text=page.text,
                trust_tier=TrustTier.NATIVE_EXACT,
                authoritative=True,
                interpretive=False,
                metadata={"page_label": page.page_label or page_label},
            )
        )
    return tuple(units)


def _build_table_units(
    ledger: CanonicalDocumentLedger,
) -> tuple[RetrievalEvidence, ...]:
    units: list[RetrievalEvidence] = []
    for page in ledger.pages:
        for block in page.blocks:
            if not isinstance(block, TableArtifact):
                continue
            text = block.markdown_projection or "\n".join(" | ".join(row) for row in block.rows)
            units.append(
                RetrievalEvidence(
                    unit_id=block.table_id,
                    document_id=ledger.document_id,
                    unit_type=RetrievalUnitType.TABLE,
                    modality=RetrievalModality.TABLE,
                    page_span=PageSpan(start_page=page.page_index, end_page=page.page_index),
                    title=f"Table {block.table_id}",
                    text=text,
                    trust_tier=_trust_tier_for_source(
                        source_track=block.provenance.source_track,
                        authoritativeness=block.provenance.content_authoritativeness,
                        confidence=block.provenance.confidence,
                    ),
                    authoritative=True,
                    interpretive=False,
                    metadata={
                        "bbox": block.bbox.model_dump(mode="json"),
                        "row_count": len(block.rows),
                    },
                )
            )
    return tuple(units)


def _visual_reference_from_block(
    *,
    document_id: str,
    page_index: int,
    visual_id: str,
    bbox: Any,
    image_ref: str | None,
    asset_path: str | None,
    page_render_path: str | None,
    render_dpi: int | None,
) -> VisualRegionReference:
    return VisualRegionReference(
        document_id=document_id,
        page_index=page_index,
        region_id=visual_id,
        bbox=bbox,
        image_ref=image_ref,
        asset_path=asset_path,
        page_render_path=page_render_path,
        render_dpi=render_dpi,
    )


def _build_visual_units(
    ledger: CanonicalDocumentLedger,
) -> tuple[RetrievalEvidence, ...]:
    units: list[RetrievalEvidence] = []
    for page in ledger.pages:
        for block in page.blocks:
            if isinstance(block, VisualArtifact):
                units.append(
                    RetrievalEvidence(
                        unit_id=block.visual_id,
                        document_id=ledger.document_id,
                        unit_type=RetrievalUnitType.VISUAL,
                        modality=RetrievalModality.VISUAL,
                        page_span=PageSpan(start_page=page.page_index, end_page=page.page_index),
                        title=block.kind_hint,
                        trust_tier=_trust_tier_for_source(
                            source_track=block.provenance.source_track,
                            authoritativeness=block.provenance.content_authoritativeness,
                            confidence=block.provenance.confidence,
                        ),
                        authoritative=False,
                        interpretive=False,
                        visual_region=_visual_reference_from_block(
                            document_id=ledger.document_id,
                            page_index=page.page_index,
                            visual_id=block.visual_id,
                            bbox=block.bbox,
                            image_ref=block.image_ref,
                            asset_path=block.asset_path,
                            page_render_path=block.page_render_path,
                            render_dpi=block.render_dpi,
                        ),
                        asset_path=block.asset_path,
                        page_render_path=block.page_render_path,
                        metadata={
                            "kind_hint": block.kind_hint,
                            "bbox": block.bbox.model_dump(mode="json"),
                            "needs_enrichment": block.needs_enrichment,
                        },
                    )
                )
            elif isinstance(block, UnresolvedRegion):
                units.append(
                    RetrievalEvidence(
                        unit_id=block.region_id,
                        document_id=ledger.document_id,
                        unit_type=RetrievalUnitType.UNRESOLVED_VISUAL,
                        modality=RetrievalModality.VISUAL,
                        page_span=PageSpan(start_page=page.page_index, end_page=page.page_index),
                        title=block.reason_code,
                        trust_tier=_trust_tier_for_source(
                            source_track=block.provenance.source_track,
                            authoritativeness=block.provenance.content_authoritativeness,
                            confidence=block.provenance.confidence,
                        ),
                        authoritative=False,
                        interpretive=False,
                        visual_region=_visual_reference_from_block(
                            document_id=ledger.document_id,
                            page_index=page.page_index,
                            visual_id=block.region_id,
                            bbox=block.bbox,
                            image_ref=None,
                            asset_path=block.asset_path,
                            page_render_path=block.page_render_path,
                            render_dpi=block.render_dpi,
                        ),
                        asset_path=block.asset_path,
                        page_render_path=block.page_render_path,
                        metadata={
                            "bbox": block.bbox.model_dump(mode="json"),
                            "reason_code": block.reason_code,
                            "recommended_fallback": block.recommended_fallback,
                            "severity": block.severity.value,
                        },
                    )
                )
    return tuple(units)


def _build_node_text_units(
    committed_nodes: tuple[HierarchyNode, ...],
    text_substrate: CanonicalTextSubstrate,
) -> tuple[RetrievalEvidence, ...]:
    pages_by_index = {page.page_index: page for page in text_substrate.pages}
    units: list[RetrievalEvidence] = []
    for node in committed_nodes:
        spans = tuple(owned_span.span for owned_span in node.owned_spans)
        text_parts = [
            _text_for_content_span(pages_by_index=pages_by_index, span=span)
            for span in spans
        ]
        text = "\n".join(part for part in text_parts if part).strip() or None
        units.append(
            RetrievalEvidence(
                unit_id=f"node-text-{node.node_id}",
                document_id=node.document_id,
                unit_type=RetrievalUnitType.NODE_TEXT,
                modality=RetrievalModality.TEXT,
                page_span=node.page_span,
                content_span=_merge_content_spans(spans),
                node_id=node.node_id,
                title=node.title,
                text=text,
                keywords=_unique_non_empty(list(node.path)),
                trust_tier=TrustTier.NATIVE_EXACT,
                authoritative=True,
                interpretive=False,
                source_anchors=_source_anchor_payloads(node.source_anchors),
                metadata={
                    "level": node.level,
                    "path": list(node.path),
                    "verified": True,
                    "owned_span_count": len(node.owned_spans),
                },
            )
        )
    return tuple(units)


def _build_node_summary_units(
    node_cards: tuple[NodeCard, ...],
    node_summaries: tuple[NodeSummary, ...],
) -> tuple[RetrievalEvidence, ...]:
    cards_by_id = {node_card.node_id: node_card for node_card in node_cards}
    units: list[RetrievalEvidence] = []
    for summary in node_summaries:
        node_card = cards_by_id.get(summary.node_id)
        if node_card is None:
            continue
        spans = tuple(owned_span.span for owned_span in node_card.owned_spans)
        units.append(
            RetrievalEvidence(
                unit_id=f"node-summary-{summary.node_id}",
                document_id=node_card.document_id,
                unit_type=RetrievalUnitType.NODE_SUMMARY,
                modality=RetrievalModality.TEXT,
                page_span=node_card.page_span,
                content_span=_merge_content_spans(spans),
                node_id=node_card.node_id,
                title=node_card.title,
                text=summary.summary,
                keywords=summary.keywords,
                authoritative=False,
                interpretive=True,
                source_anchors=_source_anchor_payloads(node_card.source_anchors),
                metadata={
                    "summary_method": summary.summary_method.value,
                    "token_count": summary.token_count,
                    "estimated_token_count": summary.estimated_token_count,
                    "exact_token_count": summary.exact_token_count,
                    "gateway_audit_path": summary.gateway_audit_path,
                },
            )
        )
    return tuple(units)


def _build_unassigned_units(
    *,
    document_id: str,
    text_substrate: CanonicalTextSubstrate,
    unassigned_spans: tuple[UnassignedPageSpan, ...],
) -> tuple[RetrievalEvidence, ...]:
    pages_by_index = {page.page_index: page for page in text_substrate.pages}
    units: list[RetrievalEvidence] = []
    for index, span in enumerate(unassigned_spans):
        units.append(
            RetrievalEvidence(
                unit_id=f"unassigned-span-{index:04d}",
                document_id=document_id,
                unit_type=RetrievalUnitType.UNASSIGNED_SPAN,
                modality=RetrievalModality.TEXT,
                page_span=span.page_span,
                title=f"Unassigned span {span.page_span.start_page}-{span.page_span.end_page}",
                text=_text_for_page_span(
                    pages_by_index=pages_by_index,
                    page_span=span.page_span,
                )
                or None,
                keywords=(span.reason,),
                trust_tier=TrustTier.NATIVE_EXACT,
                authoritative=True,
                interpretive=False,
                metadata={"reason": span.reason},
            )
        )
    return tuple(units)


class RetrievalCorpusBuilder:
    """Build and persist a retrieval corpus from acquisition and optional tree artifacts."""

    def build(
        self,
        *,
        acquisition_manifest_path: str,
        tree_manifest_path: str | None = None,
        artifact_root: str | None = None,
    ) -> RetrievalManifest:
        acquisition_manifest_file = Path(acquisition_manifest_path).resolve()
        acquisition_manifest = _load_acquisition_manifest(acquisition_manifest_file)
        tree_manifest = _load_tree_manifest(
            Path(tree_manifest_path).resolve() if tree_manifest_path is not None else None
        )
        ledger = _load_ledger(acquisition_manifest_file, acquisition_manifest)
        text_substrate = _load_text_substrate(acquisition_manifest_file, acquisition_manifest)
        committed_nodes = _load_committed_nodes(tree_manifest)
        node_cards = _load_node_cards(tree_manifest)
        node_summaries = _load_node_summaries(tree_manifest)
        verification_report = _load_verification_report(tree_manifest)
        unassigned_spans = _load_unassigned_spans(tree_manifest)

        units = (
            *_build_page_units(text_substrate),
            *_build_table_units(ledger),
            *_build_visual_units(ledger),
            *_build_node_text_units(committed_nodes, text_substrate),
            *_build_node_summary_units(node_cards, node_summaries),
            *_build_unassigned_units(
                document_id=acquisition_manifest.document_id,
                text_substrate=text_substrate,
                unassigned_spans=unassigned_spans,
            ),
        )
        corpus = RetrievalCorpus(
            document_id=acquisition_manifest.document_id,
            units=tuple(units),
        )

        retrieval_root = (
            Path(artifact_root).resolve()
            if artifact_root is not None
            else _default_retrieval_root(
                acquisition_manifest_path=acquisition_manifest_file,
                acquisition_manifest=acquisition_manifest,
                tree_manifest=tree_manifest,
            )
        )
        corpus_path = _write_json(retrieval_root / "corpus.json", corpus)
        counts_by_type = Counter(unit.unit_type.value for unit in corpus.units)
        counts_by_modality = Counter(unit.modality.value for unit in corpus.units)
        stats_path = _write_json(
            retrieval_root / "stats.json",
            {
                "document_id": corpus.document_id,
                "unit_count": len(corpus.units),
                "counts_by_type": dict(sorted(counts_by_type.items())),
                "counts_by_modality": dict(sorted(counts_by_modality.items())),
                "tree_artifacts_loaded": tree_manifest is not None,
                "verification_status": (
                    verification_report.status.value if verification_report is not None else None
                ),
                "has_node_summaries": bool(node_summaries),
                "has_unassigned_spans": bool(unassigned_spans),
                "corpus_sha256": hashlib.sha256(
                    json.dumps(
                        _json_safe(corpus),
                        sort_keys=True,
                        ensure_ascii=True,
                    ).encode("utf-8")
                ).hexdigest(),
            },
        )
        manifest = RetrievalManifest(
            document_id=corpus.document_id,
            artifact_root=str(retrieval_root),
            corpus_path=corpus_path,
            stats_path=stats_path,
            unit_count=len(corpus.units),
        )
        _write_json(retrieval_root / "manifest.json", manifest)
        return manifest


__all__ = [
    "RetrievalCorpusBuilder",
]
