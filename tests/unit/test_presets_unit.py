"""Unit coverage for public client presets."""

from __future__ import annotations

import pytest

from nullvector.presets import DocumentPreset, get_preset, list_presets, resolve_preset


def test_list_presets_exposes_expected_builtins() -> None:
    assert list_presets() == (
        "general_document",
        "academic_paper",
        "financial_report",
        "legal_contract",
    )


def test_get_preset_returns_a_copy() -> None:
    preset_a = get_preset("academic_paper")
    preset_b = get_preset("academic_paper")

    assert preset_a == preset_b
    assert preset_a is not preset_b


def test_resolve_preset_accepts_none_and_model_instances() -> None:
    general = resolve_preset(None)
    academic = get_preset("academic_paper")

    assert general.name == "general_document"
    assert resolve_preset(academic) is academic


def test_get_preset_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="unknown preset"):
        get_preset("marketing_brochure")


def test_document_preset_instances_remain_strict_models() -> None:
    preset = get_preset("legal_contract")

    assert isinstance(preset, DocumentPreset)
    assert preset.tree_settings.max_pages_per_leaf_node == 3
