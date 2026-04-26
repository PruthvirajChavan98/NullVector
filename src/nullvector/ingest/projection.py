"""Projection boundary from the canonical ledger to the tree synthesis view."""

from __future__ import annotations

import hashlib

from nullvector._text import casefold_punct_key, normalized_text_key
from nullvector.domain.events import ContentAuthoritativeness, SourceTrack, TrustTier
from nullvector.domain.ledger import (
    CanonicalDocumentLedger,
    CanonicalTextLine,
    CanonicalTextPage,
    CanonicalTextSubstrate,
    LineBlock,
    TableArtifact,
    TextBlock,
    UnresolvedRegion,
)
from nullvector.domain.tree import (
    SynthesisLine,
    SynthesisPage,
    SynthesisTextProjection,
    SynthesisTrustSummary,
    SynthesisUnresolvedRegion,
    TreeSynthesisView,
)


def _trust_tier_for_provenance(source_track: SourceTrack, confidence: float | None) -> TrustTier:
    if source_track is SourceTrack.NATIVE:
        return TrustTier.NATIVE_EXACT
    if source_track is SourceTrack.EXTERNAL_OCR:
        if confidence is not None and confidence >= 0.9:
            return TrustTier.EXTERNAL_OCR_HIGH
        if confidence is not None and confidence >= 0.75:
            return TrustTier.EXTERNAL_OCR_MEDIUM
        return TrustTier.EXTERNAL_OCR_LOW
    return TrustTier.VISUAL_INTERPRETIVE


def _line_trust_tier(line: LineBlock) -> TrustTier:
    if line.provenance.content_authoritativeness is ContentAuthoritativeness.AUTHORITATIVE:
        return TrustTier.NATIVE_EXACT
    return _trust_tier_for_provenance(line.provenance.source_track, line.provenance.confidence)


def _line_sort_key(line: LineBlock) -> tuple[int, int, str]:
    return (line.reading_index, line.occurrence_index, line.line_id)


def _page_text_from_lines(line_blocks: tuple[LineBlock, ...]) -> str:
    return "\n".join(line.content for line in sorted(line_blocks, key=_line_sort_key))


def _text_block_page_text(text_blocks: tuple[TextBlock, ...]) -> str:
    return "\n".join(block.content for block in text_blocks)


def build_canonical_text_substrate(ledger: CanonicalDocumentLedger) -> CanonicalTextSubstrate:
    """Persist the one authoritative offset-bearing text surface for downstream consumers."""

    pages: list[CanonicalTextPage] = []
    for page in ledger.pages:
        line_blocks = tuple(block for block in page.blocks if isinstance(block, LineBlock))
        text_blocks = tuple(block for block in page.blocks if isinstance(block, TextBlock))

        if line_blocks:
            ordered_lines = sorted(line_blocks, key=_line_sort_key)
            page_text = _page_text_from_lines(tuple(ordered_lines))
            substrate_lines: list[CanonicalTextLine] = []
            offset = 0
            for line in ordered_lines:
                start_offset = offset
                end_offset = start_offset + len(line.content)
                substrate_lines.append(
                    CanonicalTextLine(
                        line_id=line.line_id,
                        content=line.content,
                        normalized_text=normalized_text_key(line.content),
                        casefold_punct_text=casefold_punct_key(line.content),
                        page_index=page.page_index,
                        reading_index=line.reading_index,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        occurrence_index=line.occurrence_index,
                        bbox=line.bbox,
                        top_y=line.top_y,
                        font_size=line.font_size,
                        layout_cues_available=(
                            line.font_size is not None or line.top_y is not None
                        ),
                    )
                )
                offset = end_offset + 1
        else:
            page_text = _text_block_page_text(text_blocks)
            substrate_lines = []
            offset = 0
            for line_index, raw_line in enumerate(page_text.split("\n")):
                content = raw_line.strip()
                if not content:
                    offset += len(raw_line) + 1
                    continue
                start_offset = offset
                end_offset = start_offset + len(content)
                substrate_lines.append(
                    CanonicalTextLine(
                        line_id=f"p{page.page_index}-L{line_index}",
                        content=content,
                        normalized_text=normalized_text_key(content),
                        casefold_punct_text=casefold_punct_key(content),
                        page_index=page.page_index,
                        reading_index=line_index,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        occurrence_index=0,
                        bbox=None,
                    )
                )
                offset = end_offset + 1

        pages.append(
            CanonicalTextPage(
                page_index=page.page_index,
                page_label=page.page_label,
                text=page_text,
                text_sha256=hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
                lines=tuple(substrate_lines),
            )
        )
    return CanonicalTextSubstrate(document_id=ledger.document_id, pages=tuple(pages))


def project_ledger_to_tree_synthesis_view(ledger: CanonicalDocumentLedger) -> TreeSynthesisView:
    """Project a canonical ledger into the vendor-insulated tree synthesis boundary."""

    synthesis_pages: list[SynthesisPage] = []
    for page in ledger.pages:
        line_blocks_raw = sorted(
            (block for block in page.blocks if isinstance(block, LineBlock)),
            key=_line_sort_key,
        )
        text_blocks = tuple(block for block in page.blocks if isinstance(block, TextBlock))
        synthesis_lines: list[SynthesisLine] = []
        line_counts: dict[TrustTier, int] = {}
        offset = 0

        if line_blocks_raw:
            for line in line_blocks_raw:
                trust_tier = _line_trust_tier(line)
                start_offset = offset
                end_offset = start_offset + len(line.content)
                synthesis_lines.append(
                    SynthesisLine(
                        line_id=line.line_id,
                        content=line.content,
                        normalized_text=normalized_text_key(line.content),
                        casefold_punct_text=casefold_punct_key(line.content),
                        page_index=page.page_index,
                        reading_index=line.reading_index,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        occurrence_index=line.occurrence_index,
                        bbox=line.bbox,
                        top_y=line.top_y,
                        font_size=line.font_size,
                        layout_cues_available=(
                            line.font_size is not None or line.top_y is not None
                        ),
                        trust_tier=trust_tier,
                    )
                )
                offset = end_offset + 1
                line_counts[trust_tier] = line_counts.get(trust_tier, 0) + 1
        elif text_blocks:
            page_text = _text_block_page_text(text_blocks)
            trust_tier = _trust_tier_for_provenance(
                text_blocks[0].provenance.source_track,
                text_blocks[0].provenance.confidence,
            )
            for line_index, raw_line in enumerate(page_text.split("\n")):
                content = raw_line.strip()
                if not content:
                    offset += len(raw_line) + 1
                    continue
                start_offset = offset
                end_offset = start_offset + len(content)
                synthesis_lines.append(
                    SynthesisLine(
                        line_id=f"p{page.page_index}-L{line_index}",
                        content=content,
                        normalized_text=normalized_text_key(content),
                        casefold_punct_text=casefold_punct_key(content),
                        page_index=page.page_index,
                        reading_index=line_index,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        occurrence_index=0,
                        bbox=None,
                        trust_tier=trust_tier,
                    )
                )
                offset = end_offset + 1
                line_counts[trust_tier] = line_counts.get(trust_tier, 0) + 1

        table_projections = tuple(
            SynthesisTextProjection(
                projection_id=block.table_id,
                content=block.markdown_projection
                or "\n".join(" | ".join(row) for row in block.rows),
                reading_index=block.reading_index,
                bbox=block.bbox,
                trust_tier=_trust_tier_for_provenance(
                    block.provenance.source_track,
                    block.provenance.confidence,
                ),
            )
            for block in page.blocks
            if isinstance(block, TableArtifact)
        )
        unresolved_regions = tuple(
            SynthesisUnresolvedRegion(
                region_id=block.region_id,
                bbox=block.bbox,
                reason_code=block.reason_code,
                severity=block.severity,
                recommended_fallback=block.recommended_fallback,
            )
            for block in page.blocks
            if isinstance(block, UnresolvedRegion)
        )
        dominant_trust_tier = None
        if line_counts:
            dominant_trust_tier = max(
                line_counts.items(),
                key=lambda item: (item[1], item[0].value),
            )[0]
        synthesis_pages.append(
            SynthesisPage(
                page_index=page.page_index,
                page_label=page.page_label,
                width=page.width,
                height=page.height,
                lines=tuple(synthesis_lines),
                table_text_projections=table_projections,
                trust_summary=SynthesisTrustSummary(
                    dominant_trust_tier=dominant_trust_tier,
                    line_count_by_trust_tier=line_counts,
                    interpretive_content_present=bool(unresolved_regions),
                ),
                unresolved_regions=unresolved_regions,
            )
        )

    return TreeSynthesisView(
        document_id=ledger.document_id,
        pages=tuple(synthesis_pages),
        outline_entries=ledger.acquisition_manifest.selected_outline_entries,
        projection_events=ledger.document_events,
    )
