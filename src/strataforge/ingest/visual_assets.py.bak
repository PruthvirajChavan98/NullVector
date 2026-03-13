"""Deterministic page-render and region-crop persistence for enrichable visuals."""

from __future__ import annotations

from typing import Any, cast

import fitz

from strataforge.domain.models import (
    AcquisitionSettings,
    CanonicalDocumentLedger,
    CanonicalPage,
    PageBlock,
    UnresolvedRegion,
    VisualArtifact,
)
from strataforge.ingest.acquisition_artifacts import AcquisitionArtifactStore

fitz_module: Any = fitz


def _page_render_relative_path(*, page_index: int, dpi: int) -> str:
    return f"assets/pages/{page_index:06d}/render-{dpi}dpi.png"


def _region_asset_relative_path(*, page_index: int, region_id: str) -> str:
    return f"assets/pages/{page_index:06d}/{region_id}.png"


def _clip_rect_for_region(region: VisualArtifact | UnresolvedRegion) -> fitz.Rect:
    return cast(
        fitz.Rect,
        fitz_module.Rect(
            region.bbox.x0,
            region.bbox.y0,
            region.bbox.x1,
            region.bbox.y1,
        ),
    )


def _page_render_bytes(page: Any, *, dpi: int) -> bytes:
    return cast(bytes, page.get_pixmap(dpi=dpi, annots=False).tobytes("png"))


def _region_crop_bytes(page: Any, *, region: VisualArtifact | UnresolvedRegion, dpi: int) -> bytes:
    clip = _clip_rect_for_region(region) & page.rect
    if clip.is_empty or clip.width <= 0 or clip.height <= 0:
        return _page_render_bytes(page, dpi=dpi)
    return cast(
        bytes,
        page.get_pixmap(
            dpi=dpi,
            clip=clip,
            annots=False,
        ).tobytes("png"),
    )


def _should_materialize_asset(block: object) -> bool:
    if isinstance(block, VisualArtifact):
        return block.needs_enrichment
    return isinstance(block, UnresolvedRegion)


def _materialize_page_blocks(
    *,
    page: Any,
    canonical_page: CanonicalPage,
    store: AcquisitionArtifactStore,
    settings: AcquisitionSettings,
) -> CanonicalPage:
    relevant_blocks = tuple(
        block for block in canonical_page.blocks if _should_materialize_asset(block)
    )
    if not relevant_blocks:
        return canonical_page

    page_render_path = store.write_bytes(
        _page_render_relative_path(page_index=canonical_page.page_index, dpi=settings.render_dpi),
        _page_render_bytes(page, dpi=settings.render_dpi),
    )

    updated_blocks: list[PageBlock] = []
    for block in canonical_page.blocks:
        if isinstance(block, VisualArtifact) and block.needs_enrichment:
            asset_path = store.write_bytes(
                _region_asset_relative_path(
                    page_index=canonical_page.page_index,
                    region_id=block.visual_id,
                ),
                _region_crop_bytes(page, region=block, dpi=settings.render_dpi),
            )
            updated_blocks.append(
                block.model_copy(
                    update={
                        "asset_path": asset_path,
                        "page_render_path": page_render_path,
                        "render_dpi": settings.render_dpi,
                    }
                )
            )
            continue
        if isinstance(block, UnresolvedRegion):
            asset_path = store.write_bytes(
                _region_asset_relative_path(
                    page_index=canonical_page.page_index,
                    region_id=block.region_id,
                ),
                _region_crop_bytes(page, region=block, dpi=settings.render_dpi),
            )
            updated_blocks.append(
                block.model_copy(
                    update={
                        "asset_path": asset_path,
                        "page_render_path": page_render_path,
                        "render_dpi": settings.render_dpi,
                    }
                )
            )
            continue
        updated_blocks.append(block)
    return canonical_page.model_copy(update={"blocks": tuple(updated_blocks)})


def materialize_visual_assets(
    *,
    source_path: str,
    ledger: CanonicalDocumentLedger,
    store: AcquisitionArtifactStore,
    settings: AcquisitionSettings,
) -> CanonicalDocumentLedger:
    """Persist stable page renders and region crops for enrichable visual inputs."""

    updated_pages: list[CanonicalPage] = []
    with fitz_module.open(source_path) as document:
        for canonical_page in ledger.pages:
            page = document.load_page(canonical_page.page_index)
            updated_pages.append(
                _materialize_page_blocks(
                    page=page,
                    canonical_page=canonical_page,
                    store=store,
                    settings=settings,
                )
            )
    return ledger.model_copy(update={"pages": tuple(updated_pages)})
