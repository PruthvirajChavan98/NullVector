"""VLM page transcriber: renders PDF pages and invokes the gateway for Markdown."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, NonNegativeInt, PositiveInt

from nullvector.domain.common import (
    NonEmptyStr,
    NullVectorModel,
)
from nullvector.domain.tree import VisualRegionReference
from nullvector.ingest.page_renderer import open_pdf, render_page_to_png
from nullvector.llm.prompts.vlm_transcription import build_vlm_transcription_messages
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import RegionImageInput, TextGatewayRequest
from nullvector.storage.protocol import RunScopedStore

_ANCHOR_PATTERN = re.compile(
    r"<!--\s*SECTION_ANCHOR:\s*level\s*=\s*(\d+)\s*,\s*title\s*=\s*['\"]([^'\"]+)['\"]\s*-->"
)

_TABLE_PATTERN = re.compile(r"\|.*\|.*\n\s*\|[\s:]*-+[\s:|-]*\|")
_IMAGE_PATTERN = re.compile(r"!\[")


def _detect_tables(text: str) -> bool:
    return bool(_TABLE_PATTERN.search(text))


def _detect_images(text: str) -> bool:
    return bool(_IMAGE_PATTERN.search(text))


class SectionAnchor(NullVectorModel):
    """Structured anchor marker extracted from VLM-transcribed Markdown."""

    page_index: NonNegativeInt
    level: PositiveInt
    title: NonEmptyStr
    char_offset: NonNegativeInt


class PageTranscription(NullVectorModel):
    """VLM transcription result for a single page."""

    page_index: NonNegativeInt
    markdown_text: NonEmptyStr
    has_tables: bool = False
    has_images: bool = False
    page_render_path: NonEmptyStr | None = None
    section_anchors: tuple[SectionAnchor, ...] = Field(default_factory=tuple)


def extract_section_anchors(
    markdown_text: str,
    page_index: int,
) -> tuple[SectionAnchor, ...]:
    """Extract SECTION_ANCHOR HTML comment markers from Markdown text.

    Returns a tuple of ``SectionAnchor`` instances in document order.
    Malformed or incomplete markers are silently skipped.
    """

    anchors: list[SectionAnchor] = []
    for match in _ANCHOR_PATTERN.finditer(markdown_text):
        level = int(match.group(1))
        title = match.group(2).strip()
        if level < 1 or not title:
            continue
        anchors.append(
            SectionAnchor(
                page_index=page_index,
                level=level,
                title=title,
                char_offset=match.start(),
            )
        )
    return tuple(anchors)


@dataclass(frozen=True)
class _RenderedPage:
    """Intermediate result from the sequential render phase."""

    page_index: int
    png_bytes: bytes
    page_render_path: str | None


class VLMPageTranscriber:
    """Renders PDF pages and transcribes each via a multimodal gateway call.

    Uses ``invoke_text`` for raw Markdown output — no JSON schema enforcement.
    Table and image detection is done heuristically from the Markdown text.
    """

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
        max_concurrent_pages: int = 4,
    ) -> tuple[PageTranscription, ...]:
        """Render and transcribe all pages in a PDF.

        Pages are rendered sequentially (PyMuPDF is not thread-safe for
        concurrent page rendering from the same document handle), then
        transcribed sequentially via the gateway's ``invoke_text`` method.

        When *store* is provided, each page render is persisted as a binary
        asset and the ``page_render_path`` field is populated on the result.
        """

        with open_pdf(source_path) as document:
            total_pages: int = document.page_count
            rendered: list[_RenderedPage] = []
            for page_index in range(total_pages):
                page = document.load_page(page_index)
                png_bytes = render_page_to_png(page, dpi=self._dpi)

                page_render_path: str | None = None
                if store is not None:
                    page_render_path = store.put_binary(
                        asset_path=(f"assets/pages/{page_index:06d}/render-{self._dpi}dpi.png"),
                        content_type="image/png",
                        data=png_bytes,
                    )
                rendered.append(
                    _RenderedPage(
                        page_index=page_index,
                        png_bytes=png_bytes,
                        page_render_path=page_render_path,
                    )
                )

        return self._transcribe_pages(
            rendered_pages=rendered,
            total_pages=total_pages,
            document_id=document_id,
        )

    def _transcribe_pages(
        self,
        *,
        rendered_pages: list[_RenderedPage],
        total_pages: int,
        document_id: str,
    ) -> tuple[PageTranscription, ...]:
        """Transcribe rendered pages sequentially via invoke_text."""

        results: list[PageTranscription] = []
        for rendered in rendered_pages:
            transcription = self._transcribe_one(
                rendered=rendered,
                total_pages=total_pages,
                document_id=document_id,
            )
            results.append(transcription)
        return tuple(results)

    def _transcribe_one(
        self,
        *,
        rendered: _RenderedPage,
        total_pages: int,
        document_id: str,
    ) -> PageTranscription:
        """Transcribe a single page via invoke_text, managing temp files."""

        messages = build_vlm_transcription_messages(
            page_index=rendered.page_index,
            total_pages=total_pages,
        )
        region = VisualRegionReference(
            document_id=document_id,
            page_index=rendered.page_index,
            region_id=f"page-{rendered.page_index:06d}",
            page_render_path=rendered.page_render_path,
            render_dpi=self._dpi,
        )

        temp_file: Path | None = None
        try:
            if rendered.page_render_path is not None:
                image_path = rendered.page_render_path
            else:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(rendered.png_bytes)
                temp_file = Path(tmp.name)
                image_path = str(temp_file)

            attachment = RegionImageInput(
                region=region,
                image_path=image_path,
                media_type="image/png",
            )

            request = TextGatewayRequest(
                operation_name="vlm_page_transcription",
                messages=messages,
                attachments=(attachment,),
                temperature=0.0,
            )
            result = self._gateway.invoke_text(request)
            markdown_text = result.text.strip() or "(empty page)"

        finally:
            if temp_file is not None:
                temp_file.unlink(missing_ok=True)

        anchors = extract_section_anchors(markdown_text, rendered.page_index)

        return PageTranscription(
            page_index=rendered.page_index,
            markdown_text=markdown_text,
            has_tables=_detect_tables(markdown_text),
            has_images=_detect_images(markdown_text),
            page_render_path=rendered.page_render_path,
            section_anchors=anchors,
        )


__all__ = [
    "PageTranscription",
    "SectionAnchor",
    "VLMPageTranscriber",
    "extract_section_anchors",
]
