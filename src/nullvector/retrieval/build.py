"""Build retrieval corpora from acquisition and tree artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from logging import Logger
from pathlib import Path
from typing import Any, cast

from nullvector.domain.common import ContentSpan, PageSourceAnchor, PageSpan
from nullvector.domain.events import ContentAuthoritativeness, SourceTrack, TrustTier
from nullvector.domain.ledger import (
    AcquisitionRunManifest,
    CanonicalDocumentLedger,
    CanonicalTextPage,
    CanonicalTextSubstrate,
    TableArtifact,
    UnresolvedRegion,
    VisualArtifact,
)
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
    VisualRegionReference,
)
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.retrieval._artifacts import (
    load_acquisition_manifest,
    load_committed_nodes,
    load_ledger,
    load_node_cards,
    load_node_summaries,
    load_text_substrate,
    load_tree_manifest,
    load_unassigned_spans,
    load_verification_report,
    normalize_artifact_ref,
)
from nullvector.storage import StorageBackend, StorageConfig, build_document_store
from nullvector.storage._serialization import (
    canonical_json_text,
    is_postgres_ref,
    json_safe,
    run_identity_matches,
)
from nullvector.storage.config import PostgresStorageConfig


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
    return tuple(cast(dict[str, object], json_safe(anchor)) for anchor in anchors)


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
    acquisition_manifest_path: str,
    acquisition_manifest: AcquisitionRunManifest,
    tree_manifest: TreeBuildManifest | None,
    retrieval_run_id: str,
) -> str:
    if is_postgres_ref(acquisition_manifest_path):
        return f"retrieval/{retrieval_run_id}"
    return str(Path(acquisition_manifest_path).resolve().parent / "retrieval" / retrieval_run_id)


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
            _text_for_content_span(pages_by_index=pages_by_index, span=span) for span in spans
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

    def __init__(
        self,
        *,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._logger = resolve_runtime_logger(logger)
        self._storage = storage

    def build(
        self,
        *,
        acquisition_manifest_path: str,
        tree_manifest_path: str | None = None,
        retrieval_run_id: str | None = None,
        artifact_root: str | None = None,
    ) -> RetrievalManifest:
        input_store = build_document_store(self._storage, default_filesystem_root=".")
        acquisition_manifest_ref = cast(
            str,
            normalize_artifact_ref(acquisition_manifest_path),
        )
        tree_manifest_ref = normalize_artifact_ref(tree_manifest_path)
        acquisition_manifest = load_acquisition_manifest(input_store, acquisition_manifest_ref)
        tree_manifest = load_tree_manifest(input_store, tree_manifest_ref)
        resolved_retrieval_run_id = retrieval_run_id or (
            tree_manifest.tree_run_id
            if tree_manifest is not None
            else acquisition_manifest.acquisition_run_id
        )
        log_event(
            self._logger,
            "RetrievalCorpusBuildStarted",
            document_id=acquisition_manifest.document_id,
            retrieval_run_id=resolved_retrieval_run_id,
            tree_run_id=tree_manifest.tree_run_id if tree_manifest is not None else None,
        )
        ledger = load_ledger(input_store, acquisition_manifest)
        text_substrate = load_text_substrate(input_store, acquisition_manifest)
        committed_nodes = load_committed_nodes(input_store, tree_manifest)
        node_cards = load_node_cards(input_store, tree_manifest)
        node_summaries = load_node_summaries(input_store, tree_manifest)
        verification_report = load_verification_report(input_store, tree_manifest)
        unassigned_spans = load_unassigned_spans(input_store, tree_manifest)

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
            artifact_root
            if artifact_root is not None
            else _default_retrieval_root(
                acquisition_manifest_path=acquisition_manifest_ref,
                acquisition_manifest=acquisition_manifest,
                tree_manifest=tree_manifest,
                retrieval_run_id=resolved_retrieval_run_id,
            )
        )
        _is_postgres = isinstance(self._storage, PostgresStorageConfig)
        output_store = build_document_store(
            self._storage,
            default_filesystem_root=None if _is_postgres else str(retrieval_root),
        )
        expected_identity = {
            "document_id": acquisition_manifest.document_id,
            "acquisition_manifest_path": acquisition_manifest_ref,
            "tree_manifest_path": tree_manifest_ref,
        }
        created, run_record = output_store.reserve_run(
            run_type="retrieval",
            run_id=resolved_retrieval_run_id,
            document_id=acquisition_manifest.document_id,
            artifact_root=None if _is_postgres else str(retrieval_root),
            identity=expected_identity,
        )
        run_store = output_store.for_run(
            run_type="retrieval",
            run_id=resolved_retrieval_run_id,
            document_id=acquisition_manifest.document_id,
        )
        if not created:
            if run_identity_matches(run_record, expected_identity):
                manifest_ref = cast(
                    str | None,
                    run_record.get("manifest_ref") or run_record.get("manifest_path"),
                )
                if manifest_ref is None:
                    msg = "retrieval_run_id index points to a missing manifest"
                    raise RuntimeError(msg)
                return RetrievalManifest.model_validate_json(
                    canonical_json_text(output_store.read_json_artifact(manifest_ref))
                )
            msg = "retrieval run already exists with a different source manifest set"
            raise RuntimeError(msg)

        corpus_path = run_store.put_json(
            artifact_kind="corpus",
            artifact_path="corpus.json",
            payload=corpus,
        )
        counts_by_type = Counter(unit.unit_type.value for unit in corpus.units)
        counts_by_modality = Counter(unit.modality.value for unit in corpus.units)
        stats_path = run_store.put_json(
            artifact_kind="stats",
            artifact_path="stats.json",
            payload={
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
                        json_safe(corpus),
                        sort_keys=True,
                        ensure_ascii=True,
                    ).encode("utf-8")
                ).hexdigest(),
            },
        )
        if output_store.backend is StorageBackend.POSTGRES:
            output_store.put_retrieval_units(corpus.document_id, corpus.units)
        manifest = RetrievalManifest(
            document_id=corpus.document_id,
            artifact_root=None if _is_postgres else str(retrieval_root),
            corpus_path=corpus_path,
            stats_path=stats_path,
            unit_count=len(corpus.units),
        )
        manifest_ref = run_store.put_json(
            artifact_kind="manifest",
            artifact_path="manifest.json",
            payload=manifest,
        )
        run_store.complete(
            manifest_ref=manifest_ref,
            manifest=manifest,
        )
        log_event(
            self._logger,
            "RetrievalCorpusBuildCompleted",
            document_id=corpus.document_id,
            retrieval_run_id=resolved_retrieval_run_id,
            tree_run_id=tree_manifest.tree_run_id if tree_manifest is not None else None,
            unit_count=len(corpus.units),
            manifest_ref=manifest_ref,
            corpus_path=corpus_path,
            stats_path=stats_path,
        )
        return manifest


__all__ = [
    "RetrievalCorpusBuilder",
]
