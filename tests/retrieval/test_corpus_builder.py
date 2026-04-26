"""Retrieval corpus builder tests."""

from __future__ import annotations

import types
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


def test_retrieval_run_id_can_be_overridden(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    manifest = RetrievalCorpusBuilder().build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
        retrieval_run_id="custom-retrieval-run",
    )

    assert manifest.artifact_root is not None
    assert Path(manifest.artifact_root).name == "custom-retrieval-run"


def test_reserve_or_reuse_loads_existing_manifest_for_matching_run(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    builder = RetrievalCorpusBuilder()
    manifest = builder.build(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    inputs = builder._load_build_inputs(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    ctx, resolved_retrieval_run_id, expected_identity = builder._prepare_run_context(
        inputs,
        retrieval_run_id=None,
        artifact_root=None,
    )

    reused = builder._reserve_or_reuse(
        ctx,
        retrieval_run_id=resolved_retrieval_run_id,
        document_id=inputs.acquisition_manifest.document_id,
        expected_identity=expected_identity,
    )

    assert reused == manifest


def test_persist_and_finalize_writes_manifest_stats_and_units(tmp_path: Path) -> None:
    bundle = write_synthetic_bundle(tmp_path)
    builder = RetrievalCorpusBuilder()
    inputs = builder._load_build_inputs(
        acquisition_manifest_path=str(bundle.acquisition_manifest_path),
        tree_manifest_path=str(bundle.tree_manifest_path),
    )
    ctx, resolved_retrieval_run_id, expected_identity = builder._prepare_run_context(
        inputs,
        retrieval_run_id="phase2-persist",
        artifact_root=None,
    )
    persisted_units: list[tuple[str, tuple[object, ...]]] = []

    def fake_put_retrieval_units(
        self: object,
        document_id: str,
        units: tuple[object, ...],
    ) -> int:
        persisted_units.append((document_id, units))
        return len(units)

    ctx.store.put_retrieval_units = types.MethodType(fake_put_retrieval_units, ctx.store)  # type: ignore[method-assign]

    assert (
        builder._reserve_or_reuse(
            ctx,
            retrieval_run_id=resolved_retrieval_run_id,
            document_id=inputs.acquisition_manifest.document_id,
            expected_identity=expected_identity,
        )
        is None
    )

    corpus = builder._build_corpus(inputs)
    manifest = builder._persist_and_finalize(
        ctx,
        inputs,
        corpus,
        resolved_retrieval_run_id,
    )
    stats = ctx.store.read_json_artifact(manifest.stats_path)

    assert manifest.unit_count == len(corpus.units)
    assert Path(manifest.corpus_path).exists()
    assert Path(manifest.stats_path).exists()
    assert stats["document_id"] == inputs.acquisition_manifest.document_id
    assert stats["unit_count"] == len(corpus.units)
    assert persisted_units == [(inputs.acquisition_manifest.document_id, corpus.units)]
