"""Unit coverage for public client presets."""

from __future__ import annotations

import pytest

from nullvector.presets import DocumentPreset, get_preset, list_presets, resolve_preset


def test_list_presets_exposes_expected_builtins() -> None:
    assert list_presets() == ("general_document",)


def test_get_preset_returns_a_copy() -> None:
    preset_a = get_preset("general_document")
    preset_b = get_preset("general_document")

    assert preset_a == preset_b
    assert preset_a is not preset_b


def test_resolve_preset_accepts_none_and_model_instances() -> None:
    general = resolve_preset(None)

    assert general.name == "general_document"
    assert resolve_preset(general) is general


def test_get_preset_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="unknown preset"):
        get_preset("marketing_brochure")


def test_resolve_preset_accepts_custom_document_preset() -> None:
    """Users can construct DocumentPreset directly for any document type."""
    from nullvector.domain.tree import TreeSettings

    custom = DocumentPreset(
        name="my_custom_preset",
        tree_settings=TreeSettings(
            max_pages_per_leaf_node=4,
            max_tokens_per_leaf_node=12000,
        ),
    )

    assert resolve_preset(custom) is custom
    assert custom.tree_settings.max_pages_per_leaf_node == 4
