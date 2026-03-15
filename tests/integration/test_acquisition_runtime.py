"""Integration coverage for the parallel v2 acquisition + projection runtime."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

import pytest

from nullvector.domain import (
    AcquisitionRequest,
    TreeBuildRequest,
)
from nullvector.ingest import acquire_document
from nullvector.ingest.errors import ParseConflictError
from nullvector.tree import build_tree

PHASE01_FIXTURES = Path("fixtures/pdfs/phase01")


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        payload = getattr(record, "nullvector_event", None)
        if isinstance(payload, dict):
            self.events.append(payload)


@pytest.mark.integration
def test_acquisition_runtime_persists_ledger_projection_and_outline_artifacts(
    tmp_path: Path,
) -> None:
    manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(PHASE01_FIXTURES / "born_digital_with_outline.pdf"),
            acquisition_run_id="acquisition-outline-smoke",
            artifact_root=str(tmp_path / "acquisition-runs"),
        )
    )

    ledger = cast(dict[str, Any], _load_json(manifest.ledger_path))
    projection = cast(dict[str, Any], _load_json(manifest.projection_view_path or ""))
    selected_outline = cast(dict[str, Any], _load_json(manifest.selected_outline_path))
    assert manifest.artifact_root is not None
    run_index = cast(
        dict[str, Any],
        _load_json(str(Path(manifest.artifact_root).parent / "run-index.json")),
    )

    assert Path(manifest.ledger_path).exists()
    assert Path(manifest.projection_view_path or "").exists()
    assert Path(manifest.selected_outline_path).exists()
    assert Path(manifest.event_stream_path).exists()
    assert run_index["acquisition_run_id"] == "acquisition-outline-smoke"
    assert ledger["document_id"] == manifest.document_id
    assert projection["document_id"] == manifest.document_id
    assert len(projection["pages"]) == manifest.page_count
    assert selected_outline["selected_source"] == manifest.selected_outline_source.value
    assert any(page["lines"] for page in projection["pages"])


@pytest.mark.integration
def test_acquisition_runtime_persists_canonical_text_substrate_without_outline_augmentation(
    tmp_path: Path,
) -> None:
    manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(PHASE01_FIXTURES / "born_digital_with_outline.pdf"),
            acquisition_run_id="acquisition-canonical-text",
            artifact_root=str(tmp_path / "acquisition-runs"),
        )
    )

    substrate = cast(dict[str, Any], _load_json(manifest.canonical_text_substrate_path or ""))
    selected_outline = cast(dict[str, Any], _load_json(manifest.selected_outline_path))

    page_one = cast(dict[str, Any], substrate["pages"][1])
    page_one_lines = cast(list[dict[str, Any]], page_one["lines"])

    assert page_one["text"] == "\n".join(line["content"] for line in page_one_lines)
    assert "Details" not in [line["content"] for line in page_one_lines]
    assert selected_outline["entries"][1]["title"] == "Details"


@pytest.mark.integration
def test_acquisition_run_is_idempotent_and_conflicts_on_changed_input(tmp_path: Path) -> None:
    request = AcquisitionRequest(
        source_path=str(PHASE01_FIXTURES / "born_digital_with_outline.pdf"),
        acquisition_run_id="acquisition-idempotent",
        artifact_root=str(tmp_path / "acquisition-runs"),
    )

    first = acquire_document(request)
    second = acquire_document(request)

    assert first == second

    with pytest.raises(ParseConflictError):
        acquire_document(
            request.model_copy(
                update={
                    "source_path": str(PHASE01_FIXTURES / "born_digital_without_outline.pdf"),
                }
            )
        )

    with pytest.raises(ParseConflictError):
        acquire_document(
            request.model_copy(
                update={
                    "settings": request.settings.model_copy(update={"detect_tables": False}),
                }
            )
        )


@pytest.mark.integration
def test_tree_build_accepts_acquisition_manifest(tmp_path: Path) -> None:
    pdf_path = PHASE01_FIXTURES / "born_digital_with_outline.pdf"
    acquisition_manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(pdf_path),
            acquisition_run_id="tree-acquisition-path",
            artifact_root=str(tmp_path / "acquisition-runs"),
        )
    )
    assert acquisition_manifest.artifact_root is not None
    acquisition_tree = build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(
                Path(acquisition_manifest.artifact_root) / "manifest.json"
            ),
            tree_run_id="acquisition-tree-build",
        )
    )

    acquisition_cards = cast(list[dict[str, Any]], _load_json(acquisition_tree.node_cards_path))
    verification_report = cast(
        dict[str, Any], _load_json(acquisition_tree.verification_report_path)
    )

    assert acquisition_tree.acquisition_manifest_path == str(
        Path(acquisition_manifest.artifact_root) / "manifest.json"
    )
    assert acquisition_tree.acquisition_artifact_identity == str(
        Path(acquisition_manifest.artifact_root) / "manifest.json"
    )
    assert [card["title"] for card in acquisition_cards] == [
        "Overview",
        "Appendix",
    ]
    assert [issue["code"] for issue in verification_report["document_issues"]] == [
        "page-present-but-title-not-visible"
    ]


@pytest.mark.integration
def test_acquisition_and_tree_build_emit_expected_events(tmp_path: Path) -> None:
    logger = logging.getLogger("nullvector.test.acquisition")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    capture = _CaptureHandler()
    logger.addHandler(capture)
    manifest = acquire_document(
        AcquisitionRequest(
            source_path=str(PHASE01_FIXTURES / "born_digital_with_outline.pdf"),
            acquisition_run_id="evented-acquisition",
            artifact_root=str(tmp_path / "acquisition-runs"),
        ),
        logger=logger,
    )

    assert manifest.artifact_root is not None
    build_tree(
        TreeBuildRequest(
            acquisition_manifest_path=str(Path(manifest.artifact_root) / "manifest.json"),
            tree_run_id="evented-tree-build",
            summarize=False,
        ),
        logger=logger,
    )

    event_names = [str(event["event_name"]) for event in capture.events]

    assert event_names[:2] == [
        "SourceFingerprintComputed",
        "AcquisitionStarted",
    ]
    assert "ProjectionCreated" in event_names
    assert "HierarchyStrategySelected" in event_names
    assert "NodeCommitted" in event_names


@pytest.mark.integration
@pytest.mark.parametrize("fixture_name", ["scanned_subset.pdf", "mixed_content.pdf"])
def test_visual_regions_persist_real_attachment_assets(
    tmp_path: Path,
    fixture_name: str,
) -> None:
    request = AcquisitionRequest(
        source_path=str(PHASE01_FIXTURES / fixture_name),
        acquisition_run_id=f"visual-assets-{fixture_name.replace('.', '-')}",
        artifact_root=str(tmp_path / "acquisition-runs"),
    )

    first = acquire_document(request)
    second = acquire_document(request)
    first_ledger = cast(dict[str, Any], _load_json(first.ledger_path))
    second_ledger = cast(dict[str, Any], _load_json(second.ledger_path))

    first_assets: list[tuple[str, str, str]] = []
    second_assets: list[tuple[str, str, str]] = []

    for ledger, sink in ((first_ledger, first_assets), (second_ledger, second_assets)):
        for page in cast(list[dict[str, Any]], ledger["pages"]):
            page_blocks = cast(list[dict[str, Any]], page["blocks"])
            reading_indexes = [block["reading_index"] for block in page_blocks]
            assert reading_indexes == list(range(len(page_blocks)))
            for block in page_blocks:
                if block["block_type"] == "visual_artifact" and block["needs_enrichment"]:
                    assert block["asset_path"]
                    assert block["page_render_path"]
                    assert block["coordinate_space"] == "unrotated_page"
                    assert block["render_dpi"] == first.settings.render_dpi
                    assert Path(block["asset_path"]).exists()
                    assert Path(block["page_render_path"]).exists()
                    sink.append(
                        (
                            block["visual_id"],
                            block["asset_path"],
                            block["page_render_path"],
                        )
                    )
                if block["block_type"] == "unresolved_region":
                    assert block["asset_path"]
                    assert block["page_render_path"]
                    assert block["coordinate_space"] == "unrotated_page"
                    assert block["render_dpi"] == first.settings.render_dpi
                    assert Path(block["asset_path"]).exists()
                    assert Path(block["page_render_path"]).exists()
                    sink.append(
                        (
                            block["region_id"],
                            block["asset_path"],
                            block["page_render_path"],
                        )
                    )

    assert first_assets
    assert first_assets == second_assets
