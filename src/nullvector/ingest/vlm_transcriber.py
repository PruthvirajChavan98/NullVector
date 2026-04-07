"""VLM page transcriber: renders PDF pages and invokes the gateway for Markdown."""

from __future__ import annotations

from pydantic import NonNegativeInt

from nullvector.domain.common import (
    BoundingBox,
    GeometryCoordinateSpace,
    NonEmptyStr,
    NullVectorModel,
)
from nullvector.domain.gateway import VLMTranscriptionResponse
from nullvector.domain.tree import VisualRegionReference
from nullvector.ingest.page_renderer import open_pdf, render_page_to_png
from nullvector.llm.prompts.vlm_transcription import build_vlm_transcription_messages
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest, RegionImageInput
from nullvector.storage.protocol import RunScopedStore


class PageTranscription(NullVectorModel):
    """VLM transcription result for a single page."""

    page_index: NonNegativeInt
    markdown_text: NonEmptyStr
    has_tables: bool = False
    has_images: bool = False
    page_render_path: NonEmptyStr | None = None


class VLMPageTranscriber:
    """Renders PDF pages and transcribes each via a multimodal gateway call."""

    def __init__(
        self,
        gateway: StructuredLLMGateway,
        *,
        dpi: int = 150,
    ) -> None:
        self._gateway = gateway
        self._dpi = dpi

    def transcribe_document(
        self,
        source_path: str,
        *,
        document_id: str,
        store: RunScopedStore | None = None,
    ) -> tuple[PageTranscription, ...]:
        """Render and transcribe all pages in a PDF.

        When *store* is provided, each page render is persisted as a binary
        asset and the ``page_render_path`` field is populated on the result.
        """

        with open_pdf(source_path) as document:
            total_pages: int = document.page_count
            results: list[PageTranscription] = []
            for page_index in range(total_pages):
                page = document.load_page(page_index)
                png_bytes = render_page_to_png(page, dpi=self._dpi)

                page_render_path: str | None = None
                if store is not None:
                    page_render_path = store.put_binary(
                        asset_path=f"assets/pages/{page_index:06d}/render-{self._dpi}dpi.png",
                        content_type="image/png",
                        data=png_bytes,
                    )

                transcription = self._transcribe_page(
                    png_bytes=png_bytes,
                    page_index=page_index,
                    total_pages=total_pages,
                    document_id=document_id,
                    page_render_path=page_render_path,
                )
                results.append(transcription)

        return tuple(results)

    def _transcribe_page(
        self,
        *,
        png_bytes: bytes,
        page_index: int,
        total_pages: int,
        document_id: str,
        page_render_path: str | None,
    ) -> PageTranscription:
        """Transcribe a single rendered page via the gateway."""

        messages = build_vlm_transcription_messages(
            page_index=page_index,
            total_pages=total_pages,
        )

        # Build a dummy VisualRegionReference for the attachment.
        # Phase 5 will simplify this model to remove BoundingBox.
        region = VisualRegionReference(
            document_id=document_id,
            page_index=page_index,
            region_id=f"page-{page_index:06d}",
            bbox=BoundingBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0),
            page_render_path=page_render_path,
            render_dpi=self._dpi,
            coordinate_space=GeometryCoordinateSpace.UNROTATED_PAGE,
        )

        # Write page PNG to a temp file when no store-persisted path exists,
        # because the gateway validates that attachment paths exist on disk.
        import tempfile
        from pathlib import Path

        temp_file: Path | None = None
        if page_render_path is not None:
            image_path = page_render_path
        else:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(png_bytes)
            temp_file = Path(tmp.name)
            image_path = str(temp_file)

        attachment = RegionImageInput(
            region=region,
            image_path=image_path,
            media_type="image/png",
        )

        request: GatewayRequest[VLMTranscriptionResponse] = GatewayRequest(
            operation_name="vlm_page_transcription",
            messages=messages,
            attachments=(attachment,),
            response_model=VLMTranscriptionResponse,
            temperature=0.0,
        )
        try:
            result = self._gateway.invoke(request)
        finally:
            if temp_file is not None:
                temp_file.unlink(missing_ok=True)

        return PageTranscription(
            page_index=page_index,
            markdown_text=result.output.markdown_text,
            has_tables=result.output.has_tables,
            has_images=result.output.has_images,
            page_render_path=page_render_path,
        )


__all__ = [
    "PageTranscription",
    "VLMPageTranscriber",
]
