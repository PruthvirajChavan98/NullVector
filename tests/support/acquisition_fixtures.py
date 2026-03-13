"""Helpers for converting legacy synthetic tree fixtures into acquisition fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from nullvector.domain import (
    AcquisitionManifest,
    AcquisitionRunManifest,
    AcquisitionSettings,
    BoundingBox,
    CanonicalDocumentLedger,
    CanonicalPage,
    DocumentFingerprint,
    ExtractionProvenance,
    LineBlock,
    OutlineEntry,
    OutlineQualityReport,
    OutlineSource,
    PageLedgerRow,
    SourceMetadata,
    SourceTrack,
)
from nullvector.domain.events import ContentAuthoritativeness
from nullvector.ingest.acquisition_artifacts import settings_digest
from nullvector.ingest.projection import (
    build_canonical_text_substrate,
    project_ledger_to_tree_synthesis_view,
)
from nullvector.tree.headings import split_text_lines_with_offsets


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )


def _load_legacy_manifest(root: Path) -> dict[str, Any]:
    return cast(dict[str, Any], _read_json(root / "manifest.json"))


def _load_ledger_rows(root: Path, manifest: dict[str, Any]) -> tuple[PageLedgerRow, ...]:
    ledger_path = root / cast(str, manifest["ledger_path"])
    rows: list[PageLedgerRow] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(PageLedgerRow.model_validate_json(line))
    return tuple(rows)


def _make_line_block(
    *,
    line_id: str,
    reading_index: int,
    line: Any,
) -> LineBlock:
    return LineBlock(
        line_id=line_id,
        bbox=BoundingBox(
            x0=0.0,
            y0=float(reading_index * 14),
            x1=float(max(len(line.text), 1) * 7),
            y1=float(reading_index * 14 + 12),
        ),
        content=line.text,
        reading_index=reading_index,
        occurrence_index=line.occurrence_index,
        top_y=float(reading_index * 14),
        font_size=12.0,
        provenance=ExtractionProvenance(
            source_track=SourceTrack.NATIVE,
            producer_name="synthetic-phase02-fixture",
            content_authoritativeness=ContentAuthoritativeness.AUTHORITATIVE,
            grounded_in_native_metadata=True,
            grounded_in_bbox=True,
        ),
    )


def _page_from_row(root: Path, row: PageLedgerRow) -> CanonicalPage:
    text_path = root / row.text_artifact_path
    text = text_path.read_text(encoding="utf-8")
    line_blocks = tuple(
        _make_line_block(
            line_id=f"{row.document_id}-{row.page_index}-{index}",
            reading_index=index,
            line=line,
        )
        for index, line in enumerate(split_text_lines_with_offsets(text, row.page_index))
    )
    return CanonicalPage(
        page_index=row.page_index,
        page_label=row.page_label,
        width=612.0,
        height=792.0,
        native_available=row.native_text_available,
        blocks=line_blocks,
        events=(),
    )


def _selected_outline(root: Path) -> tuple[OutlineSource, tuple[OutlineEntry, ...]]:
    payload = cast(dict[str, Any], _read_json(root / "outline" / "selected.json"))
    selected_source = OutlineSource(cast(str, payload["selected_source"]))
    entries = tuple(
        OutlineEntry.model_validate({**entry, "source": OutlineSource(entry["source"])})
        for entry in cast(list[dict[str, Any]], payload.get("entries", []))
    )
    return selected_source, entries


def convert_legacy_parse_fixture_to_acquisition(root: Path) -> Path:
    """Rewrite a copied legacy parse fixture root into an acquisition fixture."""

    legacy_manifest = _load_legacy_manifest(root)
    fingerprint = DocumentFingerprint.model_validate(legacy_manifest["fingerprint"])
    settings = AcquisitionSettings()
    digest = settings_digest(settings)
    ledger_rows = _load_ledger_rows(root, legacy_manifest)
    selected_source, selected_outline_entries = _selected_outline(root)
    outline_reports = tuple(
        OutlineQualityReport.model_validate(
            {
                **report,
                "source": OutlineSource(cast(str, report["source"])),
            }
        )
        for report in cast(list[dict[str, Any]], legacy_manifest["outline_quality_reports"])
    )

    acquisition_manifest = AcquisitionManifest(
        source_fingerprint_sha256=fingerprint.sha256,
        settings_digest=digest,
        acquisition_provider_identity="synthetic-phase02-fixture",
        selected_outline_source=selected_source,
        outline_quality_reports=outline_reports,
        selected_outline_entries=selected_outline_entries,
        ledger_artifact_path="ledger/canonical-document-ledger.json",
        outline_artifact_paths=(
            "outline/pymupdf.normalized.json",
            "outline/pymupdf.rich.json",
            "outline/pypdf.normalized.json",
            "outline/selected.json",
        ),
        event_stream_path="events/document-events.jsonl",
    )
    pages = tuple(
        _page_from_row(root, row) for row in sorted(ledger_rows, key=lambda item: item.page_index)
    )
    canonical_ledger = CanonicalDocumentLedger(
        document_id=fingerprint.document_id,
        source_fingerprint=fingerprint,
        source_metadata=SourceMetadata(
            source_path=fingerprint.source_path,
            file_size_bytes=fingerprint.file_size_bytes,
            page_count=fingerprint.page_count,
        ),
        acquisition_manifest=acquisition_manifest,
        pages=pages,
        document_events=(),
    )
    _write_json(
        root / "ledger" / "canonical-document-ledger.json",
        canonical_ledger.model_dump(mode="json"),
    )
    (root / "events").mkdir(parents=True, exist_ok=True)
    (root / "events" / "document-events.jsonl").write_text("", encoding="utf-8")

    projection = project_ledger_to_tree_synthesis_view(canonical_ledger)
    canonical_text_substrate = build_canonical_text_substrate(canonical_ledger)
    projection_path = root / "projection" / "tree-synthesis-view.json"
    canonical_text_path = root / "projection" / "canonical-text-substrate.json"
    _write_json(canonical_text_path, canonical_text_substrate.model_dump(mode="json"))
    _write_json(projection_path, projection.model_dump(mode="json"))

    acquisition_run_manifest = AcquisitionRunManifest(
        acquisition_run_id=cast(str, legacy_manifest["parse_run_id"]),
        document_id=fingerprint.document_id,
        artifact_root=str(root),
        source_fingerprint=fingerprint,
        settings=settings,
        settings_digest=digest,
        provider_identity="synthetic-phase02-fixture",
        ledger_path=str(root / "ledger" / "canonical-document-ledger.json"),
        source_copy_path=str(root / "source" / "original.pdf"),
        event_stream_path=str(root / "events" / "document-events.jsonl"),
        selected_outline_source=selected_source,
        outline_quality_reports=outline_reports,
        selected_outline_path=str(root / "outline" / "selected.json"),
        pymupdf_outline_path=str(root / "outline" / "pymupdf.normalized.json"),
        pymupdf_rich_outline_path=str(root / "outline" / "pymupdf.rich.json"),
        pypdf_outline_path=str(root / "outline" / "pypdf.normalized.json"),
        page_count=fingerprint.page_count,
        projection_view_path=str(projection_path),
        canonical_text_substrate_path=str(canonical_text_path),
    )
    _write_json(root / "manifest.json", acquisition_run_manifest.model_dump(mode="json"))
    return root / "manifest.json"
