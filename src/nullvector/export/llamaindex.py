"""LlamaIndex edge exporters for committed NullVector outputs."""

from __future__ import annotations

import importlib
from logging import Logger
from typing import Any

from nullvector.domain.tree import NodeCard, NodeSummary, VisualEnrichmentAttachment
from nullvector.export.langchain import ExporterDependencyError, _base_metadata
from nullvector.observability.logging import log_event


def to_llamaindex_node(
    node_card: NodeCard,
    *,
    summary: NodeSummary | None = None,
    attachments: tuple[VisualEnrichmentAttachment, ...] = (),
) -> Any:
    """Project one node card into a LlamaIndex TextNode."""

    try:
        module = importlib.import_module("llama_index.core.schema")
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via tests
        msg = "LlamaIndex export requires the optional 'llama_index' dependency"
        raise ExporterDependencyError(msg) from exc
    TextNode = module.TextNode
    return TextNode(
        text=summary.summary if summary is not None else (node_card.summary or node_card.title),
        metadata=_base_metadata(node_card, summary=summary, attachments=attachments),
    )


def to_llamaindex_nodes(
    node_cards: tuple[NodeCard, ...],
    *,
    summaries_by_id: dict[str, NodeSummary] | None = None,
    attachments_by_node_id: dict[str, tuple[VisualEnrichmentAttachment, ...]] | None = None,
    logger: Logger | None = None,
) -> list[Any]:
    """Project many node cards into LlamaIndex TextNodes."""

    summaries_by_id = summaries_by_id or {}
    attachments_by_node_id = attachments_by_node_id or {}
    nodes = [
        to_llamaindex_node(
            node_card,
            summary=summaries_by_id.get(node_card.node_id),
            attachments=attachments_by_node_id.get(node_card.node_id, ()),
        )
        for node_card in node_cards
    ]
    if node_cards:
        log_event(
            logger,
            "ExportCompleted",
            document_id=node_cards[0].document_id,
            exporter_name="llamaindex",
            item_count=len(nodes),
        )
    return nodes


__all__ = [
    "ExporterDependencyError",
    "to_llamaindex_node",
    "to_llamaindex_nodes",
]
