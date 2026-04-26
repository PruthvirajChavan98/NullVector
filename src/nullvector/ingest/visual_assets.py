"""Page-render persistence for visual inputs."""

from __future__ import annotations

from nullvector.domain.ledger import (
    AcquisitionSettings,
    CanonicalDocumentLedger,
    CanonicalPage,
)
from nullvector.ingest.page_renderer import open_pdf, render_page_to_png
from nullvector.storage.protocol import RunScopedStore


def _page_render_relative_path(*, page_index: int, dpi: int) -> str:
    return f"assets/pages/{page_index:06d}/render-{dpi}dpi.png"


def materialize_visual_assets(
    *,
    source_path: str,
    ledger: CanonicalDocumentLedger,
    store: RunScopedStore,
    settings: AcquisitionSettings,
) -> CanonicalDocumentLedger:
    """Persist stable page renders for all pages in the ledger."""

    updated_pages: list[CanonicalPage] = []
    with open_pdf(source_path) as document:
        for canonical_page in ledger.pages:
            page = document.load_page(canonical_page.page_index)
            png_bytes = render_page_to_png(page, dpi=settings.render_dpi)
            store.put_binary(
                asset_path=_page_render_relative_path(
                    page_index=canonical_page.page_index,
                    dpi=settings.render_dpi,
                ),
                content_type="image/png",
                data=png_bytes,
            )
            updated_pages.append(canonical_page)
    return ledger.model_copy(update={"pages": tuple(updated_pages)})
