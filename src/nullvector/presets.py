"""Document archetype presets for the public client facade."""

from __future__ import annotations

from pydantic import Field

from nullvector.domain.common import NonEmptyStr, NullVectorModel
from nullvector.domain.ledger import AcquisitionSettings
from nullvector.domain.retrieval import DocumentDescriptionSettings
from nullvector.domain.tree import TreeSettings


class DocumentPreset(NullVectorModel):
    """One named bundle of default client-facing workflow settings."""

    name: NonEmptyStr
    acquisition_settings: AcquisitionSettings = Field(default_factory=AcquisitionSettings)
    tree_settings: TreeSettings = Field(default_factory=TreeSettings)
    tree_summarize: bool = False
    document_description_settings: DocumentDescriptionSettings = Field(
        default_factory=DocumentDescriptionSettings
    )


_PRESETS: dict[str, DocumentPreset] = {
    "general_document": DocumentPreset(name="general_document"),
}


def list_presets() -> tuple[str, ...]:
    """Return the available built-in preset names in deterministic order."""

    return tuple(_PRESETS)


def get_preset(name: str) -> DocumentPreset:
    """Return a copy of one built-in preset by name."""

    try:
        preset = _PRESETS[name]
    except KeyError as exc:
        msg = f"unknown preset {name!r}; expected one of: {', '.join(list_presets())}"
        raise ValueError(msg) from exc
    return preset.model_copy(deep=True)


def resolve_preset(preset: str | DocumentPreset | None) -> DocumentPreset:
    """Resolve one preset input to a concrete settings bundle."""

    if preset is None:
        return get_preset("general_document")
    if isinstance(preset, DocumentPreset):
        return preset
    return get_preset(preset)


__all__ = [
    "DocumentPreset",
    "get_preset",
    "list_presets",
    "resolve_preset",
]
