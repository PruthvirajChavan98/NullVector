"""Unit tests for parser substrate helpers."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from pypdf import PdfReader, PdfWriter

from nullvector.constants import EXPECTED_PYMUPDF_VERSION, EXPECTED_PYPDF_VERSION
from nullvector.domain.models import OcrMode, OutlineEntry, OutlineSource, ParserSettings
from nullvector.ingest.artifacts import settings_digest
from nullvector.ingest.errors import MissingOcrRuntimeError
from nullvector.ingest.fingerprint import fingerprint_document
from nullvector.ingest.ocr import (
    extract_ocr_rawdict,
    extract_ocr_text,
    join_ocr_languages,
    validate_ocr_runtime,
)
from nullvector.ingest.outline import (
    extract_pymupdf_outlines,
    extract_pypdf_outlines,
    score_outline,
    select_outline,
)
from nullvector.ingest.text import OcrDecision, PageAnalysis, classify_ocr_need


def phase01_fixture(name: str) -> str:
    return str(Path("fixtures/pdfs/phase01") / name)


def make_settings() -> ParserSettings:
    return ParserSettings(
        tessdata_path="/usr/share/tesseract-ocr/5/tessdata",
        pymupdf_version=EXPECTED_PYMUPDF_VERSION,
        pypdf_version=EXPECTED_PYPDF_VERSION,
    )


def make_analysis(
    *,
    native_text: str,
    native_word_count: int,
    native_char_count: int,
    has_text_blocks: bool,
    image_coverage_ratio: float,
    vector_path_count: int,
    dense_small_vector_count: int,
) -> PageAnalysis:
    return PageAnalysis(
        native_text=native_text,
        native_rawdict={"blocks": []},
        native_text_sha256="a" * 64,
        native_word_count=native_word_count,
        native_char_count=native_char_count,
        has_text_blocks=has_text_blocks,
        image_coverage_ratio=image_coverage_ratio,
        vector_path_count=vector_path_count,
        dense_small_vector_count=dense_small_vector_count,
    )


def test_fingerprint_document_is_stable() -> None:
    first = fingerprint_document(phase01_fixture("born_digital_with_outline.pdf"))
    second = fingerprint_document(phase01_fixture("born_digital_with_outline.pdf"))

    assert first == second


def test_extract_pymupdf_outlines_normalizes_toc_pages_to_zero_based() -> None:
    with fitz.open(phase01_fixture("born_digital_with_outline.pdf")) as document:  # type: ignore[no-untyped-call]
        _, entries = extract_pymupdf_outlines(document)

    assert [entry.title for entry in entries] == ["Overview", "Details", "Appendix"]
    assert [entry.page_index for entry in entries] == [0, 1, 2]
    assert all(entry.source is OutlineSource.PYMUPDF for entry in entries)


def test_extract_pypdf_outlines_flattens_nested_outline_tree(tmp_path: Path) -> None:
    fixture_path = tmp_path / "nested-outline.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=72, height=72)
    parent = writer.add_outline_item("Section 1", 0)
    writer.add_outline_item("Child 1.1", 1, parent=parent)
    writer.add_outline_item("Unresolved", None, parent=parent)
    writer.add_outline_item("Section 2", 2)
    with fixture_path.open("wb") as handle:
        writer.write(handle)

    reader = PdfReader(str(fixture_path))
    raw_outline, entries = extract_pypdf_outlines(reader)

    assert [entry.title for entry in entries] == [
        "Section 1",
        "Child 1.1",
        "Unresolved",
        "Section 2",
    ]
    assert [entry.level for entry in entries] == [1, 2, 2, 1]
    assert [entry.page_index for entry in entries] == [0, 1, None, 2]
    assert raw_outline[0]["title"] == "Section 1"
    assert raw_outline[1][0]["title"] == "Child 1.1"
    assert raw_outline[1][1]["page_index"] is None


def test_outline_scoring_prefers_lower_null_destination_rate() -> None:
    pymupdf_entries = [
        OutlineEntry(level=1, title="A", page_index=0, source=OutlineSource.PYMUPDF),
        OutlineEntry(level=2, title="B", page_index=1, source=OutlineSource.PYMUPDF),
    ]
    pypdf_entries = [
        OutlineEntry(level=1, title="A", page_index=0, source=OutlineSource.PYPDF),
        OutlineEntry(level=2, title="B", page_index=None, source=OutlineSource.PYPDF),
    ]

    selected_source, _, reports = select_outline(pymupdf_entries, pypdf_entries)

    assert selected_source is OutlineSource.PYMUPDF
    assert reports[0].score > reports[1].score


def test_score_outline_counts_invalid_level_jumps() -> None:
    report = score_outline(
        [
            OutlineEntry(level=1, title="A", page_index=0, source=OutlineSource.PYMUPDF),
            OutlineEntry(level=3, title="B", page_index=1, source=OutlineSource.PYMUPDF),
        ],
        OutlineSource.PYMUPDF,
    )

    assert report.invalid_level_count == 1


@pytest.mark.parametrize(
    ("analysis", "expected"),
    [
        (
            make_analysis(
                native_text="TITLE PAGE",
                native_word_count=2,
                native_char_count=9,
                has_text_blocks=True,
                image_coverage_ratio=0.05,
                vector_path_count=5,
                dense_small_vector_count=0,
            ),
            OcrDecision(needs_ocr=False, ocr_mode=OcrMode.NONE, reason_codes=()),
        ),
        (
            make_analysis(
                native_text="",
                native_word_count=0,
                native_char_count=0,
                has_text_blocks=False,
                image_coverage_ratio=0.99,
                vector_path_count=0,
                dense_small_vector_count=0,
            ),
            OcrDecision(
                needs_ocr=True,
                ocr_mode=OcrMode.FULL,
                reason_codes=("no_text", "low_text_density", "high_image_coverage"),
            ),
        ),
        (
            make_analysis(
                native_text="BOM",
                native_word_count=1,
                native_char_count=3,
                has_text_blocks=True,
                image_coverage_ratio=0.86,
                vector_path_count=4,
                dense_small_vector_count=0,
            ),
            OcrDecision(
                needs_ocr=True,
                ocr_mode=OcrMode.PARTIAL,
                reason_codes=("low_text_density", "high_image_coverage"),
            ),
        ),
        (
            make_analysis(
                native_text="",
                native_word_count=0,
                native_char_count=0,
                has_text_blocks=False,
                image_coverage_ratio=0.15,
                vector_path_count=2500,
                dense_small_vector_count=2300,
            ),
            OcrDecision(
                needs_ocr=True,
                ocr_mode=OcrMode.FULL,
                reason_codes=("no_text", "low_text_density", "dense_small_vectors_heuristic"),
            ),
        ),
    ],
)
def test_classify_ocr_need(analysis: PageAnalysis, expected: OcrDecision) -> None:
    decision = classify_ocr_need(analysis, make_settings())

    assert decision == expected


def test_join_ocr_languages_uses_plus_separator() -> None:
    assert join_ocr_languages(("eng", "spa")) == "eng+spa"


def test_validate_ocr_runtime_rejects_missing_tesseract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tessdata_path = tmp_path / "tessdata"
    tessdata_path.mkdir()
    (tessdata_path / "eng.traineddata").write_text("stub", encoding="utf-8")
    monkeypatch.setattr("nullvector.ingest.ocr.shutil.which", lambda _: None)

    with pytest.raises(MissingOcrRuntimeError):
        validate_ocr_runtime(
            ParserSettings(
                tessdata_path=str(tessdata_path),
                pymupdf_version=EXPECTED_PYMUPDF_VERSION,
                pypdf_version=EXPECTED_PYPDF_VERSION,
            ),
            document_id="doc-001",
            page_index=0,
        )


def test_ocr_extractors_require_textpage_argument() -> None:
    class StubPage:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def get_text(self, kind: str, *, textpage: object) -> object:
            self.calls.append((kind, textpage))
            if kind == "text":
                return "ocr text"
            return {"blocks": []}

    page = StubPage()
    textpage = object()

    assert extract_ocr_text(page, textpage) == "ocr text"
    assert extract_ocr_rawdict(page, textpage) == {"blocks": []}
    assert page.calls == [("text", textpage), ("rawdict", textpage)]


def test_settings_digest_changes_when_parser_settings_change() -> None:
    first = make_settings()
    second = first.model_copy(update={"ocr_dpi": 400})

    assert settings_digest(first) != settings_digest(second)
