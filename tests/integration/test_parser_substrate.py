"""Integration tests for the deterministic parser substrate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from strataforge.compat.legacy_parse import parse_document
from strataforge.constants import EXPECTED_PYMUPDF_VERSION, EXPECTED_PYPDF_VERSION
from strataforge.domain.models import ParseRequest, ParserSettings
from strataforge.ingest import MissingOcrRuntimeError, ParseConflictError

FIXTURE_DIR = Path("fixtures/pdfs/phase01")
EXPECTED_DIR = Path("fixtures/expected/phase01")


def load_expected(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((EXPECTED_DIR / name).read_text(encoding="utf-8")))


def tessdata_path() -> str:
    for candidate in (
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
        Path("/usr/share/tesseract-ocr/tessdata"),
    ):
        if candidate.exists():
            return str(candidate)
    raise AssertionError("tessdata path not found for OCR integration tests")


def make_settings() -> ParserSettings:
    return ParserSettings(
        tessdata_path=tessdata_path(),
        pymupdf_version=EXPECTED_PYMUPDF_VERSION,
        pypdf_version=EXPECTED_PYPDF_VERSION,
    )


def read_ledger_rows(manifest_path: Path) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], json.loads(line))
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_parse_born_digital_with_outline_persists_both_outline_sources(tmp_path: Path) -> None:
    expected = load_expected("born_digital_with_outline.json")
    manifest = parse_document(
        ParseRequest(
            source_path=str(FIXTURE_DIR / "born_digital_with_outline.pdf"),
            parse_run_id="with-outline-run",
            artifact_root=str(tmp_path / "artifacts"),
            settings=make_settings(),
        ),
    )

    selected_outline = json.loads(Path(manifest.selected_outline_path).read_text(encoding="utf-8"))
    quality_report = json.loads(
        (Path(manifest.artifact_root) / "outline" / "quality-report.json").read_text(
            encoding="utf-8"
        ),
    )
    ledger_rows = read_ledger_rows(Path(manifest.ledger_path))

    assert manifest.page_count == expected["page_count"]
    assert manifest.selected_outline_source.value == expected["selected_outline_source"]
    assert selected_outline["entries"] == expected["selected_outline"]
    assert quality_report[0]["score"] == expected["quality_reports"]["pymupdf"]["score"]
    assert quality_report[1]["score"] == expected["quality_reports"]["pypdf"]["score"]
    assert Path(manifest.pymupdf_outline_path).exists()
    assert Path(manifest.pypdf_outline_path).exists()
    assert Path(manifest.pymupdf_rich_outline_path).exists()
    assert len(ledger_rows) == 3
    assert ledger_rows[0]["extraction_method"] == "native_text"


def test_parse_writes_run_index_pointing_to_manifest(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    manifest = parse_document(
        ParseRequest(
            source_path=str(FIXTURE_DIR / "born_digital_with_outline.pdf"),
            parse_run_id="run-index-run",
            artifact_root=str(artifact_root),
            settings=make_settings(),
        ),
    )

    run_index_path = artifact_root / "run-index-run" / "run-index.json"
    run_index = json.loads(run_index_path.read_text(encoding="utf-8"))

    assert run_index_path.exists()
    assert run_index["parse_run_id"] == "run-index-run"
    assert run_index["document_id"] == manifest.document_id
    assert run_index["fingerprint_sha256"] == manifest.fingerprint.sha256
    assert run_index["settings_digest"] == manifest.settings_digest
    assert Path(run_index["manifest_path"]) == Path(manifest.artifact_root) / "manifest.json"


def test_parse_born_digital_without_outline_yields_empty_selected_outline(tmp_path: Path) -> None:
    expected = load_expected("born_digital_without_outline.json")
    manifest = parse_document(
        ParseRequest(
            source_path=str(FIXTURE_DIR / "born_digital_without_outline.pdf"),
            parse_run_id="without-outline-run",
            artifact_root=str(tmp_path / "artifacts"),
            settings=make_settings(),
        ),
    )

    selected_outline = json.loads(Path(manifest.selected_outline_path).read_text(encoding="utf-8"))
    ledger_rows = read_ledger_rows(Path(manifest.ledger_path))

    assert manifest.page_count == expected["page_count"]
    assert manifest.selected_outline_source.value == expected["selected_outline_source"]
    assert selected_outline["entries"] == []
    assert len(ledger_rows) == 2
    assert all(row["needs_ocr"] is False for row in ledger_rows)


def test_parse_native_only_document_succeeds_without_tessdata(tmp_path: Path) -> None:
    manifest = parse_document(
        ParseRequest(
            source_path=str(FIXTURE_DIR / "born_digital_without_outline.pdf"),
            parse_run_id="native-only-run",
            artifact_root=str(tmp_path / "artifacts"),
            settings=ParserSettings(
                tessdata_path=None,
                pymupdf_version=EXPECTED_PYMUPDF_VERSION,
                pypdf_version=EXPECTED_PYPDF_VERSION,
            ),
        ),
    )

    ledger_rows = read_ledger_rows(Path(manifest.ledger_path))

    assert manifest.page_count == 2
    assert all(row["needs_ocr"] is False for row in ledger_rows)


def test_parse_scanned_subset_produces_ocr_artifacts(tmp_path: Path) -> None:
    expected = load_expected("scanned_subset.json")
    manifest = parse_document(
        ParseRequest(
            source_path=str(FIXTURE_DIR / "scanned_subset.pdf"),
            parse_run_id="scanned-run",
            artifact_root=str(tmp_path / "artifacts"),
            settings=make_settings(),
        ),
    )

    ledger_rows = read_ledger_rows(Path(manifest.ledger_path))
    scanned_row = ledger_rows[1]

    assert manifest.selected_outline_source.value == expected["selected_outline_source"]
    assert ledger_rows[0]["ocr_mode"] == expected["ocr_modes"]["0"]
    assert scanned_row["ocr_mode"] == expected["ocr_modes"]["1"]
    assert scanned_row["ocr_reason_codes"] == expected["ocr_reason_codes"]["1"]
    assert Path(scanned_row["ocr_text_artifact_path"]).exists()
    assert Path(scanned_row["ocr_rawdict_artifact_path"]).exists()
    assert Path(scanned_row["ocr_render_artifact_path"]).exists()
    ocr_text = Path(scanned_row["ocr_text_artifact_path"]).read_text(encoding="utf-8")
    assert "SCANNED" in ocr_text.upper()


def test_parse_ocr_document_fails_when_tessdata_directory_is_missing(tmp_path: Path) -> None:
    with pytest.raises(MissingOcrRuntimeError):
        parse_document(
            ParseRequest(
                source_path=str(FIXTURE_DIR / "scanned_subset.pdf"),
                parse_run_id="missing-tessdata-run",
                artifact_root=str(tmp_path / "artifacts"),
                settings=ParserSettings(
                    tessdata_path=str(tmp_path / "missing-tessdata"),
                    pymupdf_version=EXPECTED_PYMUPDF_VERSION,
                    pypdf_version=EXPECTED_PYPDF_VERSION,
                ),
            ),
        )


def test_parse_mixed_content_uses_partial_ocr(tmp_path: Path) -> None:
    expected = load_expected("mixed_content.json")
    manifest = parse_document(
        ParseRequest(
            source_path=str(FIXTURE_DIR / "mixed_content.pdf"),
            parse_run_id="mixed-run",
            artifact_root=str(tmp_path / "artifacts"),
            settings=make_settings(),
        ),
    )

    ledger_rows = read_ledger_rows(Path(manifest.ledger_path))
    mixed_row = ledger_rows[0]

    assert manifest.selected_outline_source.value == expected["selected_outline_source"]
    assert mixed_row["ocr_mode"] == expected["ocr_modes"]["0"]
    assert mixed_row["ocr_reason_codes"] == expected["ocr_reason_codes"]["0"]
    assert mixed_row["extraction_method"] == "mixed"
    assert Path(mixed_row["ocr_text_artifact_path"]).exists()
    assert Path(mixed_row["native_text_artifact_path"]).exists()
    assert ledger_rows[1]["ocr_mode"] == expected["ocr_modes"]["1"]


def test_parse_rerun_is_idempotent_and_conflicts_on_setting_change(tmp_path: Path) -> None:
    request = ParseRequest(
        source_path=str(FIXTURE_DIR / "born_digital_with_outline.pdf"),
        parse_run_id="idempotent-run",
        artifact_root=str(tmp_path / "artifacts"),
        settings=make_settings(),
    )

    first = parse_document(request)
    second = parse_document(request)

    assert first == second

    changed_request = request.model_copy(
        update={
            "settings": request.settings.model_copy(update={"ocr_dpi": 450}),
        },
    )
    with pytest.raises(ParseConflictError):
        parse_document(changed_request)


def test_parse_run_id_conflicts_when_reused_for_different_document(tmp_path: Path) -> None:
    artifact_root = str(tmp_path / "artifacts")
    parse_document(
        ParseRequest(
            source_path=str(FIXTURE_DIR / "born_digital_with_outline.pdf"),
            parse_run_id="shared-run",
            artifact_root=artifact_root,
            settings=make_settings(),
        ),
    )

    with pytest.raises(ParseConflictError):
        parse_document(
            ParseRequest(
                source_path=str(FIXTURE_DIR / "born_digital_without_outline.pdf"),
                parse_run_id="shared-run",
                artifact_root=artifact_root,
                settings=make_settings(),
            ),
        )
