"""Unit coverage for Markdown-native acquisition helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from nullvector.domain import (
    AcquisitionRequest,
    AcquisitionSettings,
    MarkdownAcquisitionSettings,
    OutlineSource,
    SourceDocumentKind,
)
from nullvector.ingest._markdown import parse_markdown_source
from nullvector.ingest.fingerprint import fingerprint_document


def _write_markdown_fixture(tmp_path: Path, name: str = "sample.md") -> Path:
    source = tmp_path / name
    source.write_text(
        "\n".join(
            (
                "# Overview #",
                "Intro paragraph",
                "",
                "## Details ##",
                "- bullet one",
                "- bullet two",
                "",
                "---",
                "### Code Sample",
                "```python",
                "print('one')",
                "print('two')",
                "```",
                "",
                "Closing line",
            )
        ),
        encoding="utf-8",
    )
    return source


def test_acquisition_request_defaults_remain_pdf_compatible() -> None:
    request = AcquisitionRequest(
        source_path="fixtures/pdfs/phase01/born_digital_with_outline.pdf",
        acquisition_run_id="acq-run-001",
    )

    assert request.source_kind is SourceDocumentKind.PDF
    assert request.provider_identity == "native_pymupdf"


def test_markdown_request_requires_markdown_provider_identity() -> None:
    with pytest.raises(ValueError, match="markdown_native"):
        AcquisitionRequest(
            source_path="/tmp/example.md",
            acquisition_run_id="markdown-run",
            source_kind=SourceDocumentKind.MARKDOWN,
        )


def test_parse_markdown_source_normalizes_headings_and_splits_logical_pages(
    tmp_path: Path,
) -> None:
    source = _write_markdown_fixture(tmp_path)
    parsed = parse_markdown_source(
        str(source),
        settings=MarkdownAcquisitionSettings(
            max_logical_lines_per_page=5,
            split_on_thematic_breaks=True,
        ),
    )

    assert len(parsed.pages) == 2
    assert [entry.title for entry in parsed.outline_entries] == [
        "Overview",
        "Details",
        "Code Sample",
    ]
    assert all(entry.source is OutlineSource.MARKDOWN for entry in parsed.outline_entries)
    assert [line.content for line in parsed.pages[1].lines] == [
        "Code Sample",
        "```python",
        "print('one')",
        "print('two')",
        "Closing line",
    ]


def test_markdown_page_count_matches_parser_output(tmp_path: Path) -> None:
    source = _write_markdown_fixture(tmp_path)
    settings = AcquisitionSettings(
        markdown=MarkdownAcquisitionSettings(
            max_logical_lines_per_page=5,
            split_on_thematic_breaks=True,
        )
    )

    fingerprint = fingerprint_document(
        str(source),
        source_kind=SourceDocumentKind.MARKDOWN,
        acquisition_settings=settings,
    )
    parsed = parse_markdown_source(str(source), settings=settings.markdown)

    assert fingerprint.page_count == len(parsed.pages)
    assert fingerprint.source_path == str(source.resolve())
