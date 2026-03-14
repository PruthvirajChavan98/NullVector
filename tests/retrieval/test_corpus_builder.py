"""Retrieval corpus builder tests."""

from __future__ import annotations

from pathlib import Path

from nullvector.domain.retrieval import RetrievalUnitType
from nullvector.retrieval import RetrievalCorpusBuilder, load_retrieval_corpus

from .support import write_synthetic_bundle


def test_image_only_page_emits_visual_units(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )

    corpus = load_retrieval_corpus(manifest.corpus_path)
    page_zero_units = tuple(
        unit
        for unit in corpus.units
        if unit.page_span.start_page == 0 and unit.page_span.end_page == 0
    )

    assert any(unit.unit_type is RetrievalUnitType.VISUAL for unit in page_zero_units)
    assert not any(unit.unit_type is RetrievalUnitType.PAGE_TEXT for unit in page_zero_units)


def test_unassigned_spans_emit_retrieval_units(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )

    corpus = load_retrieval_corpus(manifest.corpus_path)
    unassigned_units = tuple(
        unit for unit in corpus.units if unit.unit_type is RetrievalUnitType.UNASSIGNED_SPAN
    )

    assert len(unassigned_units) == 1
    assert unassigned_units[0].metadata["reason"] == "before_first_heading"


def test_node_text_is_reconstructed_from_owned_spans(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )

    corpus = load_retrieval_corpus(manifest.corpus_path)
    node_text_unit = next(
        unit for unit in corpus.units if unit.unit_type is RetrievalUnitType.NODE_TEXT
    )

    assert node_text_unit.text == bundle.expected_node_text
    assert node_text_unit.text != "Appendix A summarizes the alpha and beta body lines."
