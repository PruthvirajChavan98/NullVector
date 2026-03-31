"""Semantic proxy building and lexical prefiltering before retrieval."""

from __future__ import annotations

from logging import Logger
from typing import Protocol, cast

from nullvector._hierarchy import document_order_key, path_has_prefix
from nullvector._text import collapse_whitespace, normalize_text, tokenize
from nullvector.domain.document_selection import (
    DocumentPrefilterHit,
    DocumentPrefilterRequest,
    DocumentPrefilterResponse,
    DocumentSemanticProxy,
    DocumentSemanticProxySource,
)
from nullvector.domain.retrieval import DocumentDescription
from nullvector.domain.tree import NodeCard, NodeSummary
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.retrieval._artifacts import (
    load_node_cards,
    load_node_summaries,
    load_tree_manifest,
    normalize_artifact_ref,
)
from nullvector.retrieval._selection_artifacts import (
    selection_artifact_path,
    selection_artifact_root,
)
from nullvector.retrieval.load import (
    load_document_description,
    load_document_description_manifest,
)
from nullvector.storage import StorageConfig, build_document_store

_DISPLAY_NAME_WEIGHT = 1.0
_DESCRIPTION_WEIGHT = 2.0
_SUMMARY_WEIGHT = 1.5
_KEYWORD_WEIGHT = 1.0
_EXACT_SUBSTRING_BOOST = 0.5
_MAX_TOP_LEVEL_SUMMARIES = 3
_MAX_KEYWORDS = 12
_MATCHABLE_FIELDS = (
    "display_name",
    "description_text",
    "summary_text",
    "keywords",
)


def _proxy_sort_key(proxy: DocumentSemanticProxy) -> tuple[str, str]:
    return (proxy.display_name.casefold(), proxy.document_id)


def _hit_sort_key(
    hit: DocumentPrefilterHit,
    *,
    proxies_by_id: dict[str, DocumentSemanticProxy],
) -> tuple[float, str, str]:
    proxy = proxies_by_id[hit.document_id]
    return (-hit.score, proxy.display_name.casefold(), proxy.document_id)


def _summary_text_for_card(
    node_card: NodeCard,
    summaries_by_id: dict[str, NodeSummary],
) -> str | None:
    summary = summaries_by_id.get(node_card.node_id)
    if summary is not None:
        return collapse_whitespace(summary.summary)
    if node_card.summary is not None:
        return collapse_whitespace(node_card.summary)
    return None


def _summary_keywords_for_card(
    node_card: NodeCard,
    summaries_by_id: dict[str, NodeSummary],
) -> tuple[str, ...]:
    summary = summaries_by_id.get(node_card.node_id)
    if summary is None:
        return ()
    return tuple(keyword for keyword in summary.keywords if collapse_whitespace(keyword))


def _card_keywords(node_card: NodeCard) -> tuple[str, ...]:
    return tuple(keyword for keyword in node_card.keywords if collapse_whitespace(keyword))


def _top_level_cards(node_cards: tuple[NodeCard, ...]) -> tuple[NodeCard, ...]:
    if not node_cards:
        return ()
    ordered_cards = tuple(
        sorted(
            node_cards,
            key=lambda node_card: document_order_key(
                page_span=node_card.page_span,
                level=node_card.level,
                path=node_card.path,
                identifier=node_card.node_id,
            ),
        )
    )
    top_level = tuple(node_card for node_card in ordered_cards if len(node_card.path) == 1)
    if len(top_level) == 1 and any(
        path_has_prefix(other.path, top_level[0].path) for other in ordered_cards
    ):
        root = top_level[0]
        children = tuple(
            node_card
            for node_card in ordered_cards
            if len(node_card.path) == len(root.path) + 1
            and node_card.path[: len(root.path)] == root.path
        )
        return children or (root,)
    if top_level:
        return top_level
    by_level = tuple(node_card for node_card in ordered_cards if node_card.level == 1)
    return by_level or ordered_cards


def _summary_text_from_top_level(
    top_level_cards: tuple[NodeCard, ...],
    *,
    summaries_by_id: dict[str, NodeSummary],
) -> tuple[str | None, tuple[str, ...]]:
    summary_fragments: list[str] = []
    contributing_node_ids: list[str] = []
    seen_node_ids: set[str] = set()
    for node_card in top_level_cards:
        summary_text = _summary_text_for_card(node_card, summaries_by_id)
        if summary_text is None:
            continue
        summary_fragments.append(summary_text)
        if node_card.node_id not in seen_node_ids:
            contributing_node_ids.append(node_card.node_id)
            seen_node_ids.add(node_card.node_id)
        if len(summary_fragments) >= _MAX_TOP_LEVEL_SUMMARIES:
            break
    if summary_fragments:
        return (" ".join(summary_fragments), tuple(contributing_node_ids))

    title_fragments: list[str] = []
    title_contributors: list[str] = []
    seen_titles: set[str] = set()
    for node_card in top_level_cards:
        title = collapse_whitespace(node_card.title)
        title_key = title.casefold()
        if not title or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        title_fragments.append(f"{title}." if title[-1] not in ".!?" else title)
        title_contributors.append(node_card.node_id)
        if len(title_fragments) >= _MAX_TOP_LEVEL_SUMMARIES:
            break
    if title_fragments:
        return (" ".join(title_fragments), tuple(title_contributors))
    return (None, ())


def _summary_text_without_cards(
    node_summaries: tuple[NodeSummary, ...],
) -> tuple[str | None, tuple[str, ...]]:
    summary_fragments = [
        collapse_whitespace(summary.summary)
        for summary in node_summaries[:_MAX_TOP_LEVEL_SUMMARIES]
        if collapse_whitespace(summary.summary)
    ]
    source_node_ids = tuple(summary.node_id for summary in node_summaries[: len(summary_fragments)])
    if summary_fragments:
        return (" ".join(summary_fragments), source_node_ids)
    return (None, ())


def _keywords_from_top_level(
    top_level_cards: tuple[NodeCard, ...],
    *,
    summaries_by_id: dict[str, NodeSummary],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    collected: list[str] = []
    contributing_node_ids: list[str] = []
    seen_node_ids: set[str] = set()
    seen_keywords: set[str] = set()

    def add_keywords(node_card: NodeCard, keywords: tuple[str, ...]) -> None:
        if len(collected) >= _MAX_KEYWORDS:
            return
        contributed = False
        for keyword in keywords:
            normalized = collapse_whitespace(keyword)
            if not normalized:
                continue
            keyword_key = normalized.casefold()
            if keyword_key in seen_keywords:
                continue
            seen_keywords.add(keyword_key)
            collected.append(normalized)
            contributed = True
            if len(collected) >= _MAX_KEYWORDS:
                break
        if contributed and node_card.node_id not in seen_node_ids:
            contributing_node_ids.append(node_card.node_id)
            seen_node_ids.add(node_card.node_id)

    for node_card in top_level_cards:
        add_keywords(node_card, _summary_keywords_for_card(node_card, summaries_by_id))
    for node_card in top_level_cards:
        add_keywords(node_card, _card_keywords(node_card))

    return (tuple(collected), tuple(contributing_node_ids))


def _keywords_without_cards(
    node_summaries: tuple[NodeSummary, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    collected: list[str] = []
    contributing_node_ids: list[str] = []
    seen_keywords: set[str] = set()
    for summary in node_summaries:
        contributed = False
        for keyword in summary.keywords:
            normalized = collapse_whitespace(keyword)
            keyword_key = normalized.casefold()
            if not normalized or keyword_key in seen_keywords:
                continue
            seen_keywords.add(keyword_key)
            collected.append(normalized)
            contributed = True
            if len(collected) >= _MAX_KEYWORDS:
                break
        if contributed:
            contributing_node_ids.append(summary.node_id)
        if len(collected) >= _MAX_KEYWORDS:
            break
    return (tuple(collected), tuple(contributing_node_ids))


def _build_semantic_proxy(
    *,
    source: DocumentSemanticProxySource,
    description: DocumentDescription,
    description_manifest_path: str,
    description_source_tree_manifest_path: str,
    tree_manifest_path: str,
    node_cards: tuple[NodeCard, ...],
    node_summaries: tuple[NodeSummary, ...],
) -> DocumentSemanticProxy:
    if source.document_id != description.document_id:
        msg = "semantic proxy source document_id must match description document_id"
        raise ValueError(msg)
    normalized_source_paths = tuple(
        normalized
        for normalized in (normalize_artifact_ref(ref) for ref in description.source_manifest_paths)
        if normalized is not None
    )
    if tree_manifest_path not in normalized_source_paths:
        msg = (
            "semantic proxy description artifact is stale for the provided tree manifest: "
            f"{tree_manifest_path}"
        )
        raise ValueError(msg)
    if description_source_tree_manifest_path != tree_manifest_path:
        msg = (
            "semantic proxy description manifest references a different tree manifest than "
            f"the provided source: {description_source_tree_manifest_path!r}"
        )
        raise ValueError(msg)
    if not node_cards and not node_summaries:
        msg = "semantic proxy building requires node cards or node summaries"
        raise ValueError(msg)

    summaries_by_id = {summary.node_id: summary for summary in node_summaries}
    if node_cards:
        top_level_cards = _top_level_cards(node_cards)
        summary_text, summary_node_ids = _summary_text_from_top_level(
            top_level_cards,
            summaries_by_id=summaries_by_id,
        )
        keywords, keyword_node_ids = _keywords_from_top_level(
            top_level_cards,
            summaries_by_id=summaries_by_id,
        )
    else:
        summary_text, summary_node_ids = _summary_text_without_cards(node_summaries)
        keywords, keyword_node_ids = _keywords_without_cards(node_summaries)

    if summary_text is None:
        summary_text = description.description_text

    source_node_ids: list[str] = []
    seen_source_ids: set[str] = set()
    for node_id in (*summary_node_ids, *keyword_node_ids):
        if node_id in seen_source_ids:
            continue
        seen_source_ids.add(node_id)
        source_node_ids.append(node_id)

    return DocumentSemanticProxy(
        document_id=source.document_id,
        display_name=source.display_name,
        description_text=description.description_text,
        summary_text=summary_text,
        keywords=keywords,
        source_node_ids=tuple(source_node_ids),
        description_manifest_path=description_manifest_path,
        tree_manifest_path=tree_manifest_path,
    )


def _field_match_score(
    *,
    field_text: str,
    query_tokens: tuple[str, ...],
) -> tuple[float, bool]:
    if not query_tokens:
        return (0.0, False)
    field_tokens = frozenset(tokenize(field_text))
    matched = tuple(token for token in query_tokens if token in field_tokens)
    if not matched:
        return (0.0, False)
    return (float(len(matched)) / float(len(query_tokens)), True)


def _score_proxy(
    proxy: DocumentSemanticProxy,
    *,
    query_tokens: tuple[str, ...],
    normalized_query: str,
) -> DocumentPrefilterHit:
    keyword_text = " ".join(proxy.keywords)
    field_texts = {
        "display_name": proxy.display_name,
        "description_text": proxy.description_text,
        "summary_text": proxy.summary_text,
        "keywords": keyword_text,
    }
    weights = {
        "display_name": _DISPLAY_NAME_WEIGHT,
        "description_text": _DESCRIPTION_WEIGHT,
        "summary_text": _SUMMARY_WEIGHT,
        "keywords": _KEYWORD_WEIGHT,
    }

    score = 0.0
    matched_fields: list[str] = []
    for field_name in _MATCHABLE_FIELDS:
        field_text = field_texts[field_name]
        field_score, token_match = _field_match_score(
            field_text=field_text,
            query_tokens=query_tokens,
        )
        if token_match:
            score += field_score * weights[field_name]
            matched_fields.append(field_name)
            continue
        normalized_field = normalize_text(field_text)
        if normalized_query and normalized_query in normalized_field:
            matched_fields.append(field_name)

    combined_text = normalize_text(
        " ".join(
            (
                proxy.display_name,
                proxy.description_text,
                proxy.summary_text,
                keyword_text,
            )
        )
    )
    if normalized_query and normalized_query in combined_text:
        score += _EXACT_SUBSTRING_BOOST

    return DocumentPrefilterHit(
        document_id=proxy.document_id,
        score=score,
        matched_proxy_fields=tuple(
            field_name for field_name in _MATCHABLE_FIELDS if field_name in set(matched_fields)
        ),
    )


class DocumentSemanticProxyBuilder:
    """Build deterministic semantic proxy records from descriptions and tree artifacts."""

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
        sources: tuple[DocumentSemanticProxySource, ...],
    ) -> tuple[DocumentSemanticProxy, ...]:
        log_event(
            self._logger,
            "SemanticProxyBuildStarted",
            candidate_count=len(sources),
        )
        input_store = build_document_store(self._storage, default_filesystem_root=".")
        proxies: list[DocumentSemanticProxy] = []
        for source in sources:
            description_manifest = load_document_description_manifest(
                source.description_manifest_path,
                storage=self._storage,
            )
            description = load_document_description(
                description_manifest.description_path,
                storage=self._storage,
            )
            description_manifest_path = cast(
                str,
                normalize_artifact_ref(source.description_manifest_path),
            )
            tree_manifest_path = cast(str, normalize_artifact_ref(source.tree_manifest_path))
            description_source_tree_manifest_path = cast(
                str,
                normalize_artifact_ref(description_manifest.source_tree_manifest_path),
            )
            tree_manifest = load_tree_manifest(input_store, tree_manifest_path)
            if tree_manifest is None:
                msg = "semantic proxy building requires a valid tree manifest"
                raise ValueError(msg)
            if tree_manifest.document_id != source.document_id:
                msg = "semantic proxy source document_id must match tree manifest document_id"
                raise ValueError(msg)
            node_cards = load_node_cards(input_store, tree_manifest)
            node_summaries = load_node_summaries(input_store, tree_manifest)
            proxies.append(
                _build_semantic_proxy(
                    source=source,
                    description=description,
                    description_manifest_path=description_manifest_path,
                    description_source_tree_manifest_path=description_source_tree_manifest_path,
                    tree_manifest_path=tree_manifest_path,
                    node_cards=node_cards,
                    node_summaries=node_summaries,
                )
            )
        built = tuple(proxies)
        log_event(
            self._logger,
            "SemanticProxyBuildCompleted",
            candidate_count=len(sources),
            proxy_count=len(built),
        )
        return built


class DocumentPrefilterEngine(Protocol):
    """Protocol for document-level prefilter engines."""

    def search(
        self,
        request: DocumentPrefilterRequest,
    ) -> tuple[DocumentPrefilterHit, ...]:
        """Return ranked document hits for one collection query."""


class LexicalDocumentPrefilter:
    """Deterministic lexical prefilter over persisted semantic proxy fields."""

    def search(
        self,
        request: DocumentPrefilterRequest,
    ) -> tuple[DocumentPrefilterHit, ...]:
        ordered_proxies = tuple(sorted(request.proxies, key=_proxy_sort_key))
        proxies_by_id = {proxy.document_id: proxy for proxy in ordered_proxies}
        query_tokens = tokenize(request.query)
        normalized_query = normalize_text(request.query)
        scored_hits = tuple(
            _score_proxy(
                proxy,
                query_tokens=query_tokens,
                normalized_query=normalized_query,
            )
            for proxy in ordered_proxies
        )
        positive_hits = tuple(hit for hit in scored_hits if hit.score > 0.0)
        zero_score_hits = tuple(hit for hit in scored_hits if hit.score == 0.0)
        ranked_positive = tuple(
            sorted(
                positive_hits,
                key=lambda hit: _hit_sort_key(hit, proxies_by_id=proxies_by_id),
            )
        )
        if len(ranked_positive) >= request.limit or not request.include_zero_score_fillers:
            return ranked_positive[: request.limit]
        remaining = max(request.limit - len(ranked_positive), 0)
        return ranked_positive + zero_score_hits[:remaining]


class SemanticPrefilterService:
    """Persist and execute collection-level semantic prefiltering."""

    def __init__(
        self,
        *,
        engine: DocumentPrefilterEngine | None = None,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._engine = engine or LexicalDocumentPrefilter()
        self._logger = resolve_runtime_logger(logger)
        self._storage = storage

    def select(self, request: DocumentPrefilterRequest) -> DocumentPrefilterResponse:
        log_event(
            self._logger,
            "SemanticPrefilterStarted",
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            query=request.query,
            proxy_count=len(request.proxies),
            include_zero_score_fillers=request.include_zero_score_fillers,
        )
        store = build_document_store(self._storage, default_filesystem_root=".")
        artifact_root = selection_artifact_root(
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            artifact_root=request.artifact_root,
            store=store,
        )
        index_proxies = tuple(sorted(request.proxies, key=_proxy_sort_key))
        semantic_proxy_index_path = store.put_jsonl_artifact(
            run_type="document_selection",
            run_id=request.selection_run_id,
            document_id=request.collection_id,
            artifact_kind="document_selection",
            artifact_path=selection_artifact_path(artifact_root, "semantic-proxy-index.jsonl"),
            payloads=tuple(proxy.model_dump(mode="json") for proxy in index_proxies),
        )
        hits = self._engine.search(request.model_copy(update={"proxies": index_proxies}))
        semantic_prefilter_results_path = store.put_json_artifact(
            run_type="document_selection",
            run_id=request.selection_run_id,
            document_id=request.collection_id,
            artifact_kind="document_selection",
            artifact_path=selection_artifact_path(
                artifact_root,
                "semantic-prefilter-results.json",
            ),
            payload={
                "collection_id": request.collection_id,
                "selection_run_id": request.selection_run_id,
                "query": request.query,
                "hit_count": len(hits),
                "hits": tuple(hit.model_dump(mode="json") for hit in hits),
            },
        )
        response = DocumentPrefilterResponse(
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            hits=hits,
            artifact_root=artifact_root,
            semantic_proxy_index_path=semantic_proxy_index_path,
            semantic_prefilter_results_path=semantic_prefilter_results_path,
        )
        log_event(
            self._logger,
            "SemanticPrefilterCompleted",
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            query=request.query,
            proxy_count=len(index_proxies),
            hit_count=len(hits),
            include_zero_score_fillers=request.include_zero_score_fillers,
            results_path=semantic_prefilter_results_path,
        )
        return response


__all__ = [
    "DocumentPrefilterEngine",
    "DocumentSemanticProxyBuilder",
    "LexicalDocumentPrefilter",
    "SemanticPrefilterService",
]
