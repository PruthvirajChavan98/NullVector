"""Region-aware native profiling for the parallel v2 acquisition runtime."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast

from nullvector.domain.common import BoundingBox, ScalarValue
from nullvector.domain.events import (
    ContentAuthoritativeness,
    EventSeverity,
    ExtractionProvenance,
    GroundingEvidence,
    PageEvent,
    SourceTrack,
)
from nullvector.domain.ledger import (
    CanonicalPage,
    LineBlock,
    TableArtifact,
    TextBlock,
    UnresolvedRegion,
    VisualArtifact,
)

_MULTISPACE_SPLIT = re.compile(r"\s{2,}")


@dataclass(frozen=True)
class PageProfile:
    """Internal page profile emitted by deterministic native profiling."""

    page: CanonicalPage
    unresolved_regions: tuple[UnresolvedRegion, ...]


def _bbox_from_raw(value: Any, *, fallback: BoundingBox) -> BoundingBox:
    if isinstance(value, list | tuple) and len(value) == 4:
        x0, y0, x1, y1 = value
        return BoundingBox(x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1))
    return fallback


def _page_bbox(page: Any) -> BoundingBox:
    rect = page.rect
    return BoundingBox(x0=0.0, y0=0.0, x1=float(rect.width), y1=float(rect.height))


def _text_provenance() -> ExtractionProvenance:
    return ExtractionProvenance(
        source_track=SourceTrack.NATIVE,
        producer_name="native_pymupdf",
        grounded_in_native_metadata=True,
        grounded_in_bbox=True,
        content_authoritativeness=ContentAuthoritativeness.AUTHORITATIVE,
    )


def _layout_provenance() -> ExtractionProvenance:
    return ExtractionProvenance(
        source_track=SourceTrack.NATIVE,
        producer_name="native_pymupdf",
        grounded_in_native_metadata=True,
        grounded_in_bbox=True,
        content_authoritativeness=ContentAuthoritativeness.SUPPLEMENTAL,
    )


def _table_provenance() -> ExtractionProvenance:
    return ExtractionProvenance(
        source_track=SourceTrack.NATIVE,
        producer_name="native_pymupdf",
        grounded_in_native_metadata=True,
        grounded_in_bbox=True,
        content_authoritativeness=ContentAuthoritativeness.SUPPLEMENTAL,
    )


def _visual_provenance() -> ExtractionProvenance:
    return ExtractionProvenance(
        source_track=SourceTrack.NATIVE,
        producer_name="native_pymupdf",
        grounded_in_native_metadata=True,
        grounded_in_bbox=True,
        content_authoritativeness=ContentAuthoritativeness.SUPPLEMENTAL,
    )


def _unresolved_provenance() -> ExtractionProvenance:
    return ExtractionProvenance(
        source_track=SourceTrack.NATIVE,
        producer_name="native_pymupdf",
        grounded_in_native_metadata=True,
        grounded_in_bbox=True,
        content_authoritativeness=ContentAuthoritativeness.INTERPRETIVE,
    )


def _normalize_line_key(text: str) -> str:
    return " ".join(text.split()).casefold()


def _word_count(text: str) -> int:
    return len([token for token in text.split() if token])


def _line_blocks(
    *,
    page_index: int,
    rawdict: dict[str, Any],
    fallback_bbox: BoundingBox,
) -> tuple[LineBlock, ...]:
    occurrence_counts: dict[str, int] = defaultdict(int)
    blocks: list[LineBlock] = []
    reading_index = 0
    for block in rawdict.get("blocks", []):
        if not isinstance(block, dict) or block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            if not isinstance(line, dict):
                continue
            spans = cast(list[dict[str, Any]], line.get("spans", []))
            pieces: list[str] = []
            font_sizes: list[float] = []
            font_family_hint: str | None = None
            for span in spans:
                chars = span.get("chars")
                if isinstance(chars, list) and chars:
                    pieces.append("".join(str(char.get("c", "")) for char in chars))
                else:
                    text = span.get("text")
                    if isinstance(text, str):
                        pieces.append(text)
                size = span.get("size")
                if isinstance(size, int | float):
                    font_sizes.append(float(size))
                if font_family_hint is None:
                    font_name = span.get("font")
                    if isinstance(font_name, str) and font_name.strip():
                        font_family_hint = font_name.strip()
            content = "".join(pieces).strip()
            if not content:
                continue
            bbox = _bbox_from_raw(line.get("bbox"), fallback=fallback_bbox)
            normalized = _normalize_line_key(content)
            occurrence_index = occurrence_counts[normalized]
            occurrence_counts[normalized] += 1
            blocks.append(
                LineBlock(
                    line_id=f"page-{page_index}-line-{reading_index:04d}",
                    bbox=bbox,
                    content=content,
                    reading_index=reading_index,
                    family_reading_index=reading_index,
                    occurrence_index=occurrence_index,
                    top_y=bbox.y0,
                    font_size=max(font_sizes) if font_sizes else None,
                    font_family_hint=font_family_hint,
                    provenance=_layout_provenance(),
                )
            )
            reading_index += 1
    return tuple(blocks)


def _text_blocks(
    *,
    page_index: int,
    rawdict: dict[str, Any],
    fallback_bbox: BoundingBox,
) -> tuple[TextBlock, ...]:
    blocks: list[TextBlock] = []
    reading_index = 0
    for block in rawdict.get("blocks", []):
        if not isinstance(block, dict) or block.get("type") != 0:
            continue
        lines = cast(list[dict[str, Any]], block.get("lines", []))
        line_texts: list[str] = []
        for line in lines:
            if not isinstance(line, dict):
                continue
            spans = cast(list[dict[str, Any]], line.get("spans", []))
            parts: list[str] = []
            for span in spans:
                chars = span.get("chars")
                if isinstance(chars, list) and chars:
                    parts.append("".join(str(char.get("c", "")) for char in chars))
                else:
                    text = span.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            line_text = "".join(parts).strip()
            if line_text:
                line_texts.append(line_text)
        content = "\n".join(line_texts).strip()
        if not content:
            continue
        bbox = _bbox_from_raw(block.get("bbox"), fallback=fallback_bbox)
        blocks.append(
            TextBlock(
                block_id=f"page-{page_index}-text-{reading_index:04d}",
                bbox=bbox,
                content=content,
                reading_index=reading_index,
                family_reading_index=reading_index,
                line_count=len(line_texts),
                word_count=_word_count(content),
                provenance=_text_provenance(),
                grounding=GroundingEvidence(
                    has_native_text_anchor=True,
                    has_page_bbox_anchor=True,
                    has_layout_anchor=True,
                ),
            )
        )
        reading_index += 1
    return tuple(blocks)


def _table_rows_from_block(content: str) -> tuple[tuple[str, ...], ...] | None:
    rows: list[tuple[str, ...]] = []
    expected_columns: int | None = None
    for line in content.splitlines():
        parts = tuple(part.strip() for part in _MULTISPACE_SPLIT.split(line) if part.strip())
        if len(parts) < 2:
            return None
        if expected_columns is None:
            expected_columns = len(parts)
        elif len(parts) != expected_columns:
            return None
        rows.append(parts)
    if len(rows) < 2:
        return None
    if any(any(len(cell.split()) > 12 for cell in row) for row in rows):
        return None
    numeric_column_rows = sum(
        1 for row in rows if any(any(char.isdigit() for char in cell) for cell in row[1:])
    )
    compact_rows = sum(1 for row in rows if all(len(cell.split()) <= 8 for cell in row))
    if numeric_column_rows == 0 and compact_rows < 2:
        return None
    return tuple(rows)


def _table_artifacts(
    *,
    page_index: int,
    text_blocks: tuple[TextBlock, ...],
    detect_tables: bool,
    table_min_columns: int,
    table_min_rows: int,
) -> tuple[TableArtifact, ...]:
    if not detect_tables:
        return ()
    artifacts: list[TableArtifact] = []
    for text_block in text_blocks:
        rows = _table_rows_from_block(text_block.content)
        if rows is None or len(rows) < table_min_rows or len(rows[0]) < table_min_columns:
            continue
        markdown_lines = ["| " + " | ".join(row) + " |" for row in rows]
        artifacts.append(
            TableArtifact(
                table_id=text_block.block_id.replace("text", "table", 1),
                bbox=text_block.bbox,
                reading_index=text_block.reading_index,
                family_reading_index=text_block.family_reading_index,
                rows=rows,
                markdown_projection="\n".join(markdown_lines),
                provenance=_table_provenance(),
                grounding=GroundingEvidence(
                    has_native_text_anchor=True,
                    has_page_bbox_anchor=True,
                    has_layout_anchor=True,
                ),
            )
        )
    return tuple(artifacts)


def _bbox_iou(a: BoundingBox, b: BoundingBox) -> float:
    """Intersection-over-union for two bounding boxes."""
    ix0 = max(a.x0, b.x0)
    iy0 = max(a.y0, b.y0)
    ix1 = min(a.x1, b.x1)
    iy1 = min(a.y1, b.y1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    area_a = (a.x1 - a.x0) * (a.y1 - a.y0)
    area_b = (b.x1 - b.x0) * (b.y1 - b.y0)
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return intersection / union


_IMAGE_DEDUP_IOU_THRESHOLD = 0.7


def _deduplicate_bboxes(
    bboxes: list[BoundingBox],
) -> list[int]:
    """Return indices of bboxes to keep after merging near-duplicates.

    PyMuPDF ``get_image_info()`` returns one entry per image *reference* in
    the PDF — masks, soft-masks, and repeated XObject placements produce
    multiple entries for the same visual area.  This function keeps only
    distinct visual regions by suppressing entries whose IoU with an
    already-kept entry exceeds the threshold.
    """
    kept: list[int] = []
    for i, bbox in enumerate(bboxes):
        if any(_bbox_iou(bbox, bboxes[k]) > _IMAGE_DEDUP_IOU_THRESHOLD for k in kept):
            continue
        kept.append(i)
    return kept


def _image_blocks(
    *,
    page_index: int,
    page: Any,
    fallback_bbox: BoundingBox,
) -> tuple[VisualArtifact, ...]:
    raw_infos: list[dict[str, Any]] = list(page.get_image_info())
    bboxes = [_bbox_from_raw(info.get("bbox"), fallback=fallback_bbox) for info in raw_infos]
    kept_indices = _deduplicate_bboxes(bboxes)
    blocks: list[VisualArtifact] = []
    for output_index, raw_index in enumerate(kept_indices):
        blocks.append(
            VisualArtifact(
                visual_id=f"page-{page_index}-visual-{output_index:04d}",
                bbox=bboxes[raw_index],
                reading_index=output_index,
                family_reading_index=output_index,
                kind_hint="embedded_image",
                image_ref=f"page-{page_index}-image-{raw_index:04d}",
                needs_enrichment=True,
                provenance=_visual_provenance(),
            )
        )
    return tuple(blocks)


def _dense_vector_count(page: Any, *, vector_scan_limit: int, max_area_ratio: float) -> int:
    page_area = float(page.rect.width * page.rect.height)
    if page_area <= 0:
        return 0
    dense_count = 0
    vector_count = 0
    for drawing in page.get_drawings():
        vector_count += 1
        if vector_count > vector_scan_limit:
            break
        rect = drawing.get("rect")
        if rect is None:
            continue
        area_ratio = float(rect.width * rect.height) / page_area
        if area_ratio <= max_area_ratio:
            dense_count += 1
    return dense_count


def _make_unresolved_region(
    *,
    page_index: int,
    index: int,
    bbox: BoundingBox,
    reason_code: str,
    severity: EventSeverity,
    recommended_fallback: str,
    reading_index: int | None = None,
) -> UnresolvedRegion:
    return UnresolvedRegion(
        region_id=f"page-{page_index}-unresolved-{index:04d}",
        bbox=bbox,
        reason_code=reason_code,
        severity=severity,
        recommended_fallback=recommended_fallback,
        reading_index=reading_index,
        family_reading_index=reading_index,
        provenance=_unresolved_provenance(),
    )


def _make_page_event(
    *,
    page_index: int,
    event_name: str,
    message: str,
    severity: EventSeverity,
    details: dict[str, ScalarValue],
) -> PageEvent:
    return PageEvent(
        event_id=f"page-{page_index}-{event_name}",
        event_name=event_name,
        page_index=page_index,
        severity=severity,
        message=message,
        details=details,
    )


def _block_sort_key(
    block: TextBlock | LineBlock | TableArtifact | VisualArtifact | UnresolvedRegion,
) -> tuple[float, float, int, str]:
    if isinstance(block, TextBlock):
        family_priority = 0
        stable_id = block.block_id
    elif isinstance(block, LineBlock):
        family_priority = 1
        stable_id = block.line_id
    elif isinstance(block, TableArtifact):
        family_priority = 2
        stable_id = block.table_id
    elif isinstance(block, VisualArtifact):
        family_priority = 3
        stable_id = block.visual_id
    else:
        family_priority = 4
        stable_id = block.region_id
    return (block.bbox.y0, block.bbox.x0, family_priority, stable_id)


def _assign_page_global_reading_order(
    blocks: tuple[TextBlock | LineBlock | TableArtifact | VisualArtifact | UnresolvedRegion, ...],
) -> tuple[TextBlock | LineBlock | TableArtifact | VisualArtifact | UnresolvedRegion, ...]:
    ordered = sorted(blocks, key=_block_sort_key)
    return tuple(
        block.model_copy(
            update={
                "reading_index": index,
                "family_reading_index": (
                    block.family_reading_index
                    if getattr(block, "family_reading_index", None) is not None
                    else block.reading_index
                ),
            }
        )
        for index, block in enumerate(ordered)
    )


def profile_page(
    *,
    document_id: str,
    page_index: int,
    page: Any,
    detect_tables: bool,
    table_min_columns: int,
    table_min_rows: int,
    dense_vector_threshold: int,
    small_vector_max_area_ratio: float,
    vector_scan_limit: int,
) -> PageProfile:
    """Profile a native page into canonical blocks, unresolved regions, and page events."""

    page_bbox = _page_bbox(page)
    rawdict = cast(dict[str, Any], page.get_text("rawdict"))
    text_blocks = _text_blocks(page_index=page_index, rawdict=rawdict, fallback_bbox=page_bbox)
    line_blocks = _line_blocks(page_index=page_index, rawdict=rawdict, fallback_bbox=page_bbox)
    table_artifacts = _table_artifacts(
        page_index=page_index,
        text_blocks=text_blocks,
        detect_tables=detect_tables,
        table_min_columns=table_min_columns,
        table_min_rows=table_min_rows,
    )
    visual_artifacts = _image_blocks(page_index=page_index, page=page, fallback_bbox=page_bbox)
    dense_vector_count = _dense_vector_count(
        page,
        vector_scan_limit=vector_scan_limit,
        max_area_ratio=small_vector_max_area_ratio,
    )

    unresolved_regions: list[UnresolvedRegion] = []
    page_events: list[PageEvent] = []
    if not text_blocks and visual_artifacts:
        page_events.append(
            _make_page_event(
                page_index=page_index,
                event_name="image_only_page_detected",
                message="native extraction found image-only page without usable native text",
                severity=EventSeverity.INFO,
                details={
                    "document_id": document_id,
                    "visual_artifact_count": len(visual_artifacts),
                },
            )
        )
    if dense_vector_count >= dense_vector_threshold:
        unresolved_regions.append(
            _make_unresolved_region(
                page_index=page_index,
                index=len(unresolved_regions),
                bbox=page_bbox,
                reason_code="dense_vector_region",
                severity=EventSeverity.WARNING,
                recommended_fallback="external_ocr_or_visual_enrichment",
                reading_index=0,
            )
        )
        page_events.append(
            _make_page_event(
                page_index=page_index,
                event_name="dense_vector_region_detected",
                message="native extraction found a dense vector region that may need fallback",
                severity=EventSeverity.WARNING,
                details={"document_id": document_id, "dense_vector_count": str(dense_vector_count)},
            )
        )
    if not text_blocks and not visual_artifacts and not unresolved_regions:
        unresolved_regions.append(
            _make_unresolved_region(
                page_index=page_index,
                index=0,
                bbox=page_bbox,
                reason_code="no_recoverable_native_content",
                severity=EventSeverity.WARNING,
                recommended_fallback="external_ocr_or_visual_enrichment",
                reading_index=0,
            )
        )
        page_events.append(
            _make_page_event(
                page_index=page_index,
                event_name="no_recoverable_native_content",
                message="native extraction recovered no text, visuals, or deterministic table data",
                severity=EventSeverity.WARNING,
                details={"document_id": document_id},
            )
        )

    unordered_blocks: tuple[
        TextBlock | LineBlock | TableArtifact | VisualArtifact | UnresolvedRegion, ...
    ] = (
        *text_blocks,
        *line_blocks,
        *table_artifacts,
        *visual_artifacts,
        *unresolved_regions,
    )
    blocks = _assign_page_global_reading_order(unordered_blocks)
    canonical_page = CanonicalPage(
        page_index=page_index,
        page_label=page.get_label(),
        width=float(page.rect.width),
        height=float(page.rect.height),
        rotation=float(page.rotation),
        native_available=bool(text_blocks or line_blocks),
        blocks=blocks,
        events=tuple(page_events),
    )
    return PageProfile(page=canonical_page, unresolved_regions=tuple(unresolved_regions))
