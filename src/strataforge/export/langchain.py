"""LangChain edge exporters for committed NullVector outputs."""

from __future__ import annotations

import importlib
from typing import Any

from nullvector.domain.models import NodeCard, NodeSummary, VisualEnrichmentAttachment
from nullvector.observability import EventBus, ExportCompleted


class ExporterDependencyError(RuntimeError):
    """Raised when an optional exporter dependency is unavailable."""


def _attachment_payload(
    attachments: tuple[VisualEnrichmentAttachment, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "attachment_id": attachment.attachment_id,
            "region_id": attachment.region_id,
            "node_id": attachment.node_id,
            "provider_identity": attachment.provider_identity,
            "confidence": attachment.confidence,
            "summary": attachment.insight.summary,
            "labels": list(attachment.insight.labels),
            "attributes": attachment.insight.attributes,
            "audit_path": attachment.audit_path,
        }
        for attachment in attachments
    ]


def _base_metadata(
    node_card: NodeCard,
    *,
    summary: NodeSummary | None,
    attachments: tuple[VisualEnrichmentAttachment, ...],
) -> dict[str, Any]:
    return {
        "node_id": node_card.node_id,
        "document_id": node_card.document_id,
        "path": list(node_card.path),
        "level": node_card.level,
        "title": node_card.title,
        "page_span": {
            "start_page": node_card.page_span.start_page,
            "end_page": node_card.page_span.end_page,
        },
        "owned_spans": [
            {
                "kind": owned_span.kind,
                "start_page": owned_span.span.start_page,
                "start_offset": owned_span.span.start_offset,
                "end_page": owned_span.span.end_page,
                "end_offset": owned_span.span.end_offset,
            }
            for owned_span in node_card.owned_spans
        ],
        "source_anchors": [
            {
                "page": anchor.page,
                "start_offset": anchor.start_offset,
                "end_offset": anchor.end_offset,
                "quote": anchor.quote,
            }
            for anchor in node_card.source_anchors
        ],
        "summary_method": node_card.summary_method.value if node_card.summary_method else None,
        "summary_token_count": node_card.summary_token_count,
        "summary_usage": (
            {
                "token_count": summary.token_count,
                "estimated_token_count": summary.estimated_token_count,
                "exact_token_count": summary.exact_token_count,
                "tokenizer_identity": summary.tokenizer_identity,
                "gateway_provider_name": summary.gateway_provider_name,
                "gateway_assurance_mode": summary.gateway_assurance_mode,
                "gateway_audit_path": summary.gateway_audit_path,
                "gateway_usage": (
                    summary.gateway_usage.model_dump(mode="json")
                    if summary.gateway_usage is not None
                    else None
                ),
            }
            if summary is not None
            else None
        ),
        "visual_enrichments": _attachment_payload(attachments),
    }


def to_langchain_document(
    node_card: NodeCard,
    *,
    summary: NodeSummary | None = None,
    attachments: tuple[VisualEnrichmentAttachment, ...] = (),
) -> Any:
    """Project one node card into a LangChain Document."""

    try:
        module = importlib.import_module("langchain_core.documents")
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via tests
        msg = "LangChain export requires the optional 'langchain_core' dependency"
        raise ExporterDependencyError(msg) from exc
    Document = module.Document
    page_content = (
        summary.summary if summary is not None else (node_card.summary or node_card.title)
    )
    return Document(
        page_content=page_content,
        metadata=_base_metadata(node_card, summary=summary, attachments=attachments),
    )


def to_langchain_documents(
    node_cards: tuple[NodeCard, ...],
    *,
    summaries_by_id: dict[str, NodeSummary] | None = None,
    attachments_by_node_id: dict[str, tuple[VisualEnrichmentAttachment, ...]] | None = None,
    event_bus: EventBus | None = None,
) -> list[Any]:
    """Project many node cards into LangChain Documents."""

    summaries_by_id = summaries_by_id or {}
    attachments_by_node_id = attachments_by_node_id or {}
    documents = [
        to_langchain_document(
            node_card,
            summary=summaries_by_id.get(node_card.node_id),
            attachments=attachments_by_node_id.get(node_card.node_id, ()),
        )
        for node_card in node_cards
    ]
    if event_bus is not None and node_cards:
        event_bus.publish(
            ExportCompleted(
                event_id=f"{node_cards[0].document_id}-langchain-export",
                event_name="ExportCompleted",
                document_id=node_cards[0].document_id,
                exporter_name="langchain",
                item_count=len(documents),
            )
        )
    return documents


__all__ = [
    "ExporterDependencyError",
    "to_langchain_document",
    "to_langchain_documents",
]
