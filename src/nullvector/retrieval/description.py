"""Build document-description artifacts from acquisition and tree outputs."""

from __future__ import annotations

from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Any, cast

from nullvector._hierarchy import document_order_key, path_has_prefix
from nullvector._text import collapse_whitespace
from nullvector.domain.retrieval import (
    DocumentDescription,
    DocumentDescriptionManifest,
    DocumentDescriptionMethod,
    DocumentDescriptionRequest,
)
from nullvector.domain.tree import NodeCard, NodeSummary
from nullvector.llm.prompts.document_description import (
    DocumentDescriptionPromptResponse,
    build_document_description_messages,
)
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.retrieval._artifacts import (
    load_acquisition_manifest,
    load_node_cards,
    load_node_summaries,
    load_tree_manifest,
    normalize_artifact_ref,
)
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage._serialization import (
    canonical_json_text,
    is_postgres_ref,
    run_identity_matches,
    settings_digest,
)
from nullvector.storage.config import PostgresStorageConfig


@dataclass(frozen=True)
class _SelectedSourceNode:
    """Internal normalized source node payload used for prompts and fallbacks."""

    node_id: str
    title: str | None
    path: tuple[str, ...]
    page_span: dict[str, int] | None
    summary_text: str | None
    keywords: tuple[str, ...]
    source_quotes: tuple[str, ...]


def _page_span_width(node_card: NodeCard) -> int:
    return node_card.page_span.end_page - node_card.page_span.start_page


def _summary_text_for_card(
    node_card: NodeCard,
    summaries_by_id: dict[str, NodeSummary],
) -> str | None:
    summary = summaries_by_id.get(node_card.node_id)
    if summary is not None:
        return summary.summary
    if node_card.summary is not None:
        return collapse_whitespace(node_card.summary)
    return None


def _keywords_for_card(
    node_card: NodeCard,
    summaries_by_id: dict[str, NodeSummary],
) -> tuple[str, ...]:
    summary = summaries_by_id.get(node_card.node_id)
    if summary is not None and summary.keywords:
        return tuple(summary.keywords)
    return tuple(node_card.keywords)


def _source_quotes_for_card(node_card: NodeCard) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for anchor in node_card.source_anchors:
        normalized = collapse_whitespace(anchor.quote)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def _selected_source_from_card(
    node_card: NodeCard,
    summaries_by_id: dict[str, NodeSummary],
) -> _SelectedSourceNode:
    return _SelectedSourceNode(
        node_id=node_card.node_id,
        title=node_card.title,
        path=tuple(node_card.path),
        page_span=node_card.page_span.model_dump(mode="json"),
        summary_text=_summary_text_for_card(node_card, summaries_by_id),
        keywords=_keywords_for_card(node_card, summaries_by_id),
        source_quotes=_source_quotes_for_card(node_card),
    )


def _select_source_nodes(
    node_cards: tuple[NodeCard, ...],
    node_summaries: tuple[NodeSummary, ...],
    *,
    max_source_nodes: int,
) -> tuple[_SelectedSourceNode, ...]:
    summaries_by_id = {summary.node_id: summary for summary in node_summaries}
    if not node_cards:
        return tuple(
            _SelectedSourceNode(
                node_id=summary.node_id,
                title=None,
                path=(),
                page_span=None,
                summary_text=summary.summary,
                keywords=tuple(summary.keywords),
                source_quotes=(),
            )
            for summary in node_summaries[:max_source_nodes]
        )

    ordered_cards = sorted(
        node_cards,
        key=lambda node_card: document_order_key(
            page_span=node_card.page_span,
            level=node_card.level,
            path=node_card.path,
            identifier=node_card.node_id,
        ),
    )
    root_candidate: NodeCard | None = None
    top_level_cards = tuple(node_card for node_card in ordered_cards if len(node_card.path) == 1)
    if len(top_level_cards) == 1 and any(
        path_has_prefix(other.path, top_level_cards[0].path) for other in ordered_cards
    ):
        root_candidate = top_level_cards[0]

    if root_candidate is not None:
        first_level_cards = tuple(
            node_card
            for node_card in ordered_cards
            if len(node_card.path) == len(root_candidate.path) + 1
            and node_card.path[: len(root_candidate.path)] == root_candidate.path
        )
    else:
        first_level_cards = top_level_cards or tuple(
            node_card for node_card in ordered_cards if node_card.level == 1
        )

    selected_ids: set[str] = set()
    selected: list[_SelectedSourceNode] = []

    def add_card(node_card: NodeCard) -> None:
        if node_card.node_id in selected_ids or len(selected) >= max_source_nodes:
            return
        selected_ids.add(node_card.node_id)
        selected.append(_selected_source_from_card(node_card, summaries_by_id))

    if root_candidate is not None:
        add_card(root_candidate)
    for node_card in first_level_cards:
        add_card(node_card)

    summarized_leaf_cards = sorted(
        (
            node_card
            for node_card in ordered_cards
            if _summary_text_for_card(node_card, summaries_by_id) is not None
            and not any(path_has_prefix(other.path, node_card.path) for other in ordered_cards)
        ),
        key=lambda node_card: (
            -_page_span_width(node_card),
            *document_order_key(
                page_span=node_card.page_span,
                level=node_card.level,
                path=node_card.path,
                identifier=node_card.node_id,
            ),
        ),
    )
    for node_card in summarized_leaf_cards:
        add_card(node_card)

    return tuple(selected[:max_source_nodes])


def _build_prompt_sources(
    selected_sources: tuple[_SelectedSourceNode, ...],
    *,
    use_summaries: bool,
) -> tuple[dict[str, Any], ...]:
    payloads: list[dict[str, Any]] = []
    for source in selected_sources:
        payload: dict[str, Any] = {
            "node_id": source.node_id,
            "title": source.title,
            "path": list(source.path),
            "page_span": source.page_span,
        }
        if use_summaries and source.summary_text is not None:
            payload["summary"] = source.summary_text
            if source.keywords:
                payload["keywords"] = list(source.keywords)
        else:
            if source.summary_text is not None and source.title is None:
                payload["summary"] = source.summary_text
            if source.source_quotes:
                payload["source_quotes"] = list(source.source_quotes)
            if source.keywords:
                payload["keywords"] = list(source.keywords)
        payloads.append(payload)
    return tuple(payloads)


def _build_deterministic_description(
    selected_sources: tuple[_SelectedSourceNode, ...],
) -> str:
    unique_titles: list[str] = []
    seen_titles: set[str] = set()
    first_summary: str | None = None
    first_quote: str | None = None

    for source in selected_sources:
        if source.title is not None:
            normalized_title = collapse_whitespace(source.title)
            if normalized_title and normalized_title not in seen_titles:
                seen_titles.add(normalized_title)
                unique_titles.append(normalized_title)
        if first_summary is None and source.summary_text is not None:
            first_summary = collapse_whitespace(source.summary_text)
        if first_quote is None and source.source_quotes:
            first_quote = source.source_quotes[0]

    sentences: list[str] = []
    if unique_titles:
        sentences.append(f"Sections include {', '.join(unique_titles)}.")
    if first_summary:
        summary_sentence = first_summary
        if summary_sentence[-1] not in ".!?":
            summary_sentence = f"{summary_sentence}."
        sentences.append(summary_sentence)
    elif first_quote:
        quote_sentence = first_quote
        if quote_sentence[-1] not in ".!?":
            quote_sentence = f"{quote_sentence}."
        sentences.append(quote_sentence)

    description = " ".join(sentences).strip()
    if description:
        return description
    if selected_sources:
        fallback_subject = selected_sources[0].title or selected_sources[0].node_id
        return f"Document focused on {fallback_subject}."
    return "Document description unavailable."


def _default_description_root(
    *,
    request: DocumentDescriptionRequest,
    tree_manifest_ref: str,
) -> str:
    if is_postgres_ref(tree_manifest_ref):
        return f"document_description/{request.description_run_id}"
    return str(
        Path(tree_manifest_ref).resolve().parent / "description" / request.description_run_id
    )


class DocumentDescriptionBuilder:
    """Build and persist document-description artifacts from tree outputs."""

    def __init__(
        self,
        *,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._logger = resolve_runtime_logger(logger)
        self._storage = storage

    def build(
        self,
        request: DocumentDescriptionRequest,
        *,
        gateway: StructuredLLMGateway | None = None,
    ) -> DocumentDescriptionManifest:
        if gateway is None and request.settings.require_gateway:
            msg = "document descriptions require a gateway when require_gateway=True"
            raise ValueError(msg)

        input_store = build_document_store(self._storage, default_filesystem_root=".")
        acquisition_manifest_ref = cast(
            str,
            normalize_artifact_ref(request.acquisition_manifest_path),
        )
        tree_manifest_ref = cast(str, normalize_artifact_ref(request.tree_manifest_path))

        acquisition_manifest = load_acquisition_manifest(input_store, acquisition_manifest_ref)
        tree_manifest = load_tree_manifest(input_store, tree_manifest_ref)
        if tree_manifest is None:
            msg = "document descriptions require a valid tree manifest"
            raise ValueError(msg)
        if tree_manifest.document_id != acquisition_manifest.document_id:
            msg = "tree and acquisition manifests must reference the same document_id"
            raise ValueError(msg)
        log_event(
            self._logger,
            "DocumentDescriptionBuildStarted",
            document_id=acquisition_manifest.document_id,
            description_run_id=request.description_run_id,
            tree_run_id=tree_manifest.tree_run_id,
        )

        node_cards = load_node_cards(input_store, tree_manifest)
        node_summaries = load_node_summaries(input_store, tree_manifest)
        if not node_cards and not node_summaries:
            msg = "document descriptions require node cards or node summaries"
            raise ValueError(msg)

        source_nodes = _select_source_nodes(
            node_cards,
            node_summaries,
            max_source_nodes=request.settings.max_source_nodes,
        )
        if not source_nodes:
            msg = "document descriptions require at least one selected source node"
            raise ValueError(msg)

        settings_hash = settings_digest(request.settings)
        description_root = (
            request.artifact_root
            if request.artifact_root is not None
            else _default_description_root(
                request=request,
                tree_manifest_ref=tree_manifest_ref,
            )
        )
        _is_postgres = isinstance(self._storage, PostgresStorageConfig)
        output_store = (
            input_store
            if _is_postgres
            else build_document_store(
                self._storage,
                default_filesystem_root=str(description_root),
            )
        )
        expected_identity = {
            "document_id": acquisition_manifest.document_id,
            "acquisition_manifest_path": acquisition_manifest_ref,
            "tree_manifest_path": tree_manifest_ref,
            "settings_digest": settings_hash,
        }
        created, run_record = output_store.reserve_run(
            run_type="document_description",
            run_id=request.description_run_id,
            document_id=acquisition_manifest.document_id,
            artifact_root=None if _is_postgres else str(description_root),
            identity=expected_identity,
        )
        run_store = output_store.for_run(
            run_type="document_description",
            run_id=request.description_run_id,
            document_id=acquisition_manifest.document_id,
        )
        if not created:
            if run_identity_matches(run_record, expected_identity):
                manifest_ref = cast(
                    str | None,
                    run_record.get("manifest_ref") or run_record.get("manifest_path"),
                )
                if manifest_ref is None:
                    msg = "document description run index points to a missing manifest"
                    raise RuntimeError(msg)
                return DocumentDescriptionManifest.model_validate_json(
                    canonical_json_text(output_store.read_json_artifact(manifest_ref))
                )
            msg = "document description run already exists with a different source manifest set"
            raise RuntimeError(msg)

        use_summaries = request.settings.prefer_node_summaries and any(
            source.summary_text is not None for source in source_nodes
        )
        source_node_ids = tuple(source.node_id for source in source_nodes)

        if gateway is None:
            description_text = _build_deterministic_description(source_nodes)
            method = DocumentDescriptionMethod.DETERMINISTIC_FALLBACK
        else:
            prompt_sources = _build_prompt_sources(source_nodes, use_summaries=use_summaries)
            gateway_result = gateway.invoke(
                GatewayRequest[DocumentDescriptionPromptResponse](
                    operation_name="document_description",
                    messages=build_document_description_messages(
                        document_id=acquisition_manifest.document_id,
                        source_nodes=prompt_sources,
                    ),
                    response_model=DocumentDescriptionPromptResponse,
                    max_output_tokens=request.settings.max_output_tokens,
                    metadata={
                        "document_id": acquisition_manifest.document_id,
                        "source_node_count": len(source_nodes),
                    },
                    idempotency_key=request.description_run_id,
                )
            )
            invalid_node_ids = tuple(
                node_id
                for node_id in gateway_result.output.supporting_node_ids
                if node_id not in source_node_ids
            )
            if invalid_node_ids:
                msg = (
                    "document_description returned supporting_node_ids outside the "
                    f"selected source set: {invalid_node_ids}"
                )
                raise ValueError(msg)
            description_text = gateway_result.output.description_text
            method = (
                DocumentDescriptionMethod.LLM_FROM_SUMMARIES
                if use_summaries
                else DocumentDescriptionMethod.LLM_FROM_NODE_CARDS
            )

        description = DocumentDescription(
            document_id=acquisition_manifest.document_id,
            tree_run_id=tree_manifest.tree_run_id,
            source_manifest_paths=(acquisition_manifest_ref, tree_manifest_ref),
            description_text=description_text,
            description_method=method,
            source_node_ids=source_node_ids,
            settings_digest=settings_hash,
        )
        description_path = run_store.put_json(
            artifact_kind="description",
            artifact_path="description/document-description.json",
            payload=description,
        )
        manifest = DocumentDescriptionManifest(
            document_id=acquisition_manifest.document_id,
            description_run_id=request.description_run_id,
            artifact_root=None if _is_postgres else str(description_root),
            description_path=description_path,
            source_tree_manifest_path=tree_manifest_ref,
            source_acquisition_manifest_path=acquisition_manifest_ref,
        )
        manifest_ref = run_store.put_json(
            artifact_kind="manifest",
            artifact_path="manifest.json",
            payload=manifest,
        )
        run_store.complete(manifest_ref=manifest_ref, manifest=manifest)
        log_event(
            self._logger,
            "DocumentDescriptionBuildCompleted",
            document_id=acquisition_manifest.document_id,
            description_run_id=request.description_run_id,
            tree_run_id=tree_manifest.tree_run_id,
            description_method=method.value,
            source_node_count=len(source_node_ids),
            manifest_ref=manifest_ref,
        )
        return manifest


__all__ = [
    "DocumentDescriptionBuilder",
]
