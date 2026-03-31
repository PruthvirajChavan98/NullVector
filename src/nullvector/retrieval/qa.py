"""Answer synthesis over retrieval hits."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from logging import Logger

from nullvector._text import normalize_text
from nullvector.domain.common import NonEmptyStr, NullVectorModel, PageSpan
from nullvector.domain.retrieval import (
    AnswerCitation,
    DocumentDescription,
    QueryIntent,
    QueryPlan,
    RetrievalCorpus,
    RetrievalEvidence,
    RetrievalHit,
    RetrievalUnitType,
)
from nullvector.domain.tree import VisualEnrichmentRequest
from nullvector.llm.errors import GatewayError
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.visual import enrich_visual_region
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.retrieval.service import RetrievalService


def _page_label_for_span(page_span: PageSpan) -> str:
    """Derive a human-readable page label from a zero-indexed page span."""

    start_page = page_span.start_page + 1
    end_page = page_span.end_page + 1
    return str(start_page) if start_page == end_page else f"{start_page}-{end_page}"


def _excerpt_for_hit(hit: RetrievalHit, query: str) -> str | None:
    text = hit.unit.text
    if text is None or not text.strip():
        return None
    normalized_query_terms = tuple(term for term in normalize_text(query).split() if term)
    best_line = ""
    best_score = -1
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        line_terms = set(normalize_text(stripped).split())
        score = len(set(normalized_query_terms) & line_terms)
        if score > best_score:
            best_line = stripped
            best_score = score
    excerpt = best_line or text.strip().splitlines()[0]
    return excerpt[:280]


def _distinct_hits_by_unit(
    hits: tuple[RetrievalHit, ...],
    *,
    limit: int,
) -> tuple[RetrievalHit, ...]:
    selected: list[RetrievalHit] = []
    seen_units: set[str] = set()
    for hit in hits:
        unit_id = hit.unit.unit_id
        if unit_id in seen_units:
            continue
        seen_units.add(unit_id)
        selected.append(hit)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _grounding_priority(hit: RetrievalHit, *, prefer_tables: bool) -> tuple[int, float]:
    if prefer_tables:
        if hit.unit.unit_type is RetrievalUnitType.TABLE:
            return (0, -hit.score)
        if hit.unit.unit_type in {
            RetrievalUnitType.NODE_TEXT,
            RetrievalUnitType.PAGE_TEXT,
            RetrievalUnitType.UNASSIGNED_SPAN,
        }:
            return (1, -hit.score)
    else:
        if hit.unit.unit_type in {
            RetrievalUnitType.NODE_TEXT,
            RetrievalUnitType.PAGE_TEXT,
            RetrievalUnitType.UNASSIGNED_SPAN,
        }:
            return (0, -hit.score)
        if hit.unit.unit_type is RetrievalUnitType.TABLE:
            return (1, -hit.score)
    if hit.unit.unit_type is RetrievalUnitType.NODE_SUMMARY:
        return (2, -hit.score)
    return (3, -hit.score)


def _grounding_key(hit: RetrievalHit, *, query: str) -> str:
    excerpt = _excerpt_for_hit(hit, query)
    if excerpt is not None:
        normalized_excerpt = normalize_text(excerpt)
        if normalized_excerpt:
            return f"excerpt:{normalized_excerpt}"
    if hit.unit.title:
        normalized_title = normalize_text(hit.unit.title)
        if normalized_title:
            return f"title:{normalized_title}"
    return f"unit:{hit.unit.unit_id}"


def _select_grounding_hits(
    hits: tuple[RetrievalHit, ...],
    *,
    query: str,
    prefer_tables: bool,
    limit: int,
) -> tuple[RetrievalHit, ...]:
    text_like_types = {
        RetrievalUnitType.NODE_TEXT,
        RetrievalUnitType.PAGE_TEXT,
        RetrievalUnitType.UNASSIGNED_SPAN,
        RetrievalUnitType.NODE_SUMMARY,
    }
    if prefer_tables:
        primary_hits = tuple(hit for hit in hits if hit.unit.unit_type is RetrievalUnitType.TABLE)
        fallback_hits = tuple(hit for hit in hits if hit.unit.unit_type in text_like_types)
    else:
        primary_hits = tuple(hit for hit in hits if hit.unit.unit_type in text_like_types)
        fallback_hits = tuple(hit for hit in hits if hit.unit.unit_type is RetrievalUnitType.TABLE)
    candidate_hits = primary_hits or fallback_hits or hits
    prioritized = tuple(
        sorted(
            candidate_hits,
            key=lambda hit: _grounding_priority(hit, prefer_tables=prefer_tables),
        )
    )
    selected: list[RetrievalHit] = []
    seen_keys: set[str] = set()
    for hit in prioritized:
        grounding_key = _grounding_key(hit, query=query)
        if grounding_key in seen_keys:
            continue
        seen_keys.add(grounding_key)
        selected.append(hit)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _has_lexical_evidence(hit: RetrievalHit) -> bool:
    return any(
        hit.score_breakdown.get(key, 0.0) > 0.0
        for key in ("quoted_phrase_match", "title_match", "keyword_overlap", "token_overlap")
    )


def _compose_grounded_text_answer(
    hits: tuple[RetrievalHit, ...],
    *,
    query: str,
    max_parts: int = 3,
) -> str:
    parts: list[str] = []
    seen_texts: set[str] = set()
    for hit in _distinct_hits_by_unit(hits, limit=max_parts):
        excerpt = _excerpt_for_hit(hit, query)
        if excerpt is None:
            excerpt = hit.unit.title
        if excerpt is None:
            continue
        normalized_excerpt = normalize_text(excerpt)
        if not normalized_excerpt or normalized_excerpt in seen_texts:
            continue
        seen_texts.add(normalized_excerpt)
        title = hit.unit.title
        if title and normalize_text(title) not in normalized_excerpt:
            parts.append(f"{title}: {excerpt}")
        else:
            parts.append(excerpt)
    if not parts:
        return "Grounded evidence was found, but no answerable text excerpt is available."
    if len(parts) == 1:
        return parts[0]
    return " ".join(parts)


def _node_text_sort_key(unit: RetrievalEvidence) -> tuple[int, int, int, str, str]:
    level_value = unit.metadata.get("level")
    level = level_value if isinstance(level_value, int) else 99
    return (
        unit.page_span.start_page,
        unit.page_span.end_page,
        level,
        unit.title or "",
        unit.unit_id,
    )


def _document_summary_from_corpus(corpus: RetrievalCorpus) -> str | None:
    summary_units = tuple(
        unit
        for unit in corpus.units
        if unit.unit_type is RetrievalUnitType.NODE_SUMMARY and unit.text and unit.title
    )
    if summary_units:
        ordered_summaries = tuple(
            sorted(
                summary_units,
                key=lambda unit: (
                    unit.page_span.start_page,
                    unit.page_span.end_page,
                    unit.title or "",
                    unit.unit_id,
                ),
            )
        )
        sections: list[str] = []
        summaries: list[str] = []
        seen_titles: set[str] = set()
        for unit in ordered_summaries:
            title = unit.title or ""
            title_key = normalize_text(title)
            if title_key and title_key not in seen_titles:
                seen_titles.add(title_key)
                sections.append(title)
            if unit.text:
                summaries.append(unit.text.strip())
            if len(sections) >= 4 and len(summaries) >= 2:
                break
        sentences: list[str] = []
        if sections:
            sentences.append(f"This document covers {', '.join(sections)}.")
        if summaries:
            sentences.extend(
                summary if summary[-1:] in ".!?" else f"{summary}." for summary in summaries[:2]
            )
        return " ".join(sentences).strip() or None

    node_text_units = tuple(
        unit
        for unit in corpus.units
        if unit.unit_type is RetrievalUnitType.NODE_TEXT and unit.title and unit.text
    )
    if not node_text_units:
        return None
    ordered_units = tuple(
        sorted(
            node_text_units,
            key=lambda unit: _node_text_sort_key(unit),
        )
    )
    node_sections: list[str] = []
    excerpts: list[str] = []
    node_seen_titles: set[str] = set()
    for unit in ordered_units:
        title = unit.title or ""
        title_key = normalize_text(title)
        if title_key and title_key not in node_seen_titles:
            node_seen_titles.add(title_key)
            node_sections.append(title)
        unit_text = unit.text or ""
        excerpt = unit_text.strip().splitlines()[0] if unit_text.strip() else ""
        if excerpt:
            excerpts.append(excerpt[:220])
        if len(node_sections) >= 4 and len(excerpts) >= 2:
            break
    if not node_sections and not excerpts:
        return None
    node_sentences: list[str] = []
    if node_sections:
        node_sentences.append(
            f"This document includes sections such as {', '.join(node_sections)}."
        )
    if excerpts:
        node_sentences.extend(
            excerpt if excerpt[-1:] in ".!?" else f"{excerpt}." for excerpt in excerpts[:2]
        )
    return " ".join(node_sentences).strip() or None


class QAResponse(NullVectorModel):
    """Grounded answer payload returned by retrieval QA."""

    answer: NonEmptyStr
    citations: tuple[AnswerCitation, ...] = ()
    retrieval_hits: tuple[RetrievalHit, ...] = ()
    answer_mode: NonEmptyStr
    answer_strategy: NonEmptyStr | None = None


class RetrievalQAService:
    """Synthesize grounded answers from retrieval hits."""

    def __init__(
        self,
        retrieval_service: RetrievalService,
        gateway: StructuredLLMGateway | None = None,
        document_description: DocumentDescription | None = None,
        description_resolver: Callable[[str], DocumentDescription | None] | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._gateway = gateway
        self._document_description = document_description
        self._description_resolver = description_resolver
        self._logger = resolve_runtime_logger(logger)

    def answer(
        self,
        *,
        corpus: RetrievalCorpus,
        query: str,
        limit: int = 5,
    ) -> QAResponse:
        log_event(
            self._logger,
            "RetrievalQAStarted",
            document_id=corpus.document_id,
            query=query,
            limit=limit,
        )
        plan = self._retrieval_service.plan(corpus=corpus, query=query)
        if plan.query_intent is QueryIntent.DOCUMENT_SUMMARY:
            response = self._document_summary_response(corpus=corpus, query=query)
            return self._log_response(corpus.document_id, query, plan, response)
        hits = self._retrieval_service.search(corpus=corpus, query=query, limit=limit)
        if not hits:
            response = QAResponse(
                answer="No grounded evidence was found in the current corpus.",
                citations=(),
                retrieval_hits=(),
                answer_mode="no_hits",
                answer_strategy="grounded_no_hits",
            )
            return self._log_response(corpus.document_id, query, plan, response)

        if plan.query_intent in {
            QueryIntent.TOPIC_LOOKUP,
            QueryIntent.SECTION_LOOKUP,
            QueryIntent.QUOTE_LOOKUP,
        } and not any(_has_lexical_evidence(hit) for hit in hits):
            response = QAResponse(
                answer=(
                    "Grounded evidence exists in the current corpus, but the query did not match "
                    "strongly enough to support a reliable answer."
                ),
                citations=(),
                retrieval_hits=hits,
                answer_mode="low_evidence",
                answer_strategy="grounded_low_evidence",
            )
            return self._log_response(corpus.document_id, query, plan, response)

        if plan.visual_query:
            visual_hits = tuple(
                hit
                for hit in hits
                if hit.unit.unit_type
                in {
                    RetrievalUnitType.VISUAL,
                    RetrievalUnitType.UNRESOLVED_VISUAL,
                }
            )
            if not visual_hits:
                response = QAResponse(
                    answer="No visual evidence was found for the requested scope.",
                    citations=(),
                    retrieval_hits=hits,
                    answer_mode="visual_no_hits",
                    answer_strategy="visual_no_hits",
                )
                return self._log_response(corpus.document_id, query, plan, response)
            top_visual = visual_hits[0]
            if top_visual.unit.text and top_visual.unit.interpretive:
                citation = self._citation_for_hit(top_visual, query=query)
                response = QAResponse(
                    answer=top_visual.unit.text,
                    citations=(citation,),
                    retrieval_hits=hits,
                    answer_mode="cached_visual_attachment",
                    answer_strategy="cached_visual_attachment",
                )
                return self._log_response(corpus.document_id, query, plan, response)
            if self._gateway is not None and top_visual.unit.visual_region is not None:
                try:
                    enriched = self._enrich_visual_hit(hit=top_visual, query=query)
                except GatewayError:
                    enriched = None
                except Exception:
                    enriched = None
                if enriched is not None:
                    return self._log_response(corpus.document_id, query, plan, enriched)
            response = self._visual_interpretation_unavailable_response(
                hit=top_visual,
                query=query,
                retrieval_hits=hits,
            )
            return self._log_response(corpus.document_id, query, plan, response)

        authoritative_hits = tuple(
            hit
            for hit in hits
            if hit.unit.authoritative
            and hit.unit.unit_type
            in {
                RetrievalUnitType.PAGE_TEXT,
                RetrievalUnitType.NODE_TEXT,
                RetrievalUnitType.TABLE,
                RetrievalUnitType.UNASSIGNED_SPAN,
            }
        )
        citations_source = _select_grounding_hits(
            authoritative_hits if authoritative_hits else hits,
            query=query,
            prefer_tables=plan.table_query,
            limit=3,
        )
        answer = _compose_grounded_text_answer(citations_source, query=query)
        response = QAResponse(
            answer=answer,
            citations=tuple(self._citation_for_hit(hit, query=query) for hit in citations_source),
            retrieval_hits=hits,
            answer_mode=(
                "authoritative_text"
                if len(citations_source) == 1 and authoritative_hits
                else "grounded_multi_excerpt"
            )
            if authoritative_hits
            else "interpretive_fallback",
            answer_strategy=(
                "multi_excerpt_grounded" if len(citations_source) > 1 else "single_excerpt_grounded"
            ),
        )
        return self._log_response(corpus.document_id, query, plan, response)

    def _citation_for_hit(self, hit: RetrievalHit, *, query: str) -> AnswerCitation:
        return AnswerCitation(
            document_id=hit.unit.document_id,
            unit_id=hit.unit.unit_id,
            page_span=hit.unit.page_span,
            page_label=_page_label_for_span(hit.unit.page_span),
            node_id=hit.unit.node_id,
            quote=_excerpt_for_hit(hit, query),
            asset_path=hit.unit.asset_path,
        )

    def _visual_interpretation_unavailable_response(
        self,
        *,
        hit: RetrievalHit,
        query: str,
        retrieval_hits: tuple[RetrievalHit, ...],
    ) -> QAResponse:
        citation = self._citation_for_hit(hit, query=query)
        return QAResponse(
            answer=(
                f"Page {citation.page_label} contains visual evidence, but no grounded visual "
                "interpretation is available in the current corpus."
            ),
            citations=(citation,),
            retrieval_hits=retrieval_hits,
            answer_mode="visual_interpretation_unavailable",
            answer_strategy="visual_interpretation_unavailable",
        )

    def _enrich_visual_hit(self, *, hit: RetrievalHit, query: str) -> QAResponse | None:
        if self._gateway is None or hit.unit.visual_region is None:
            return None
        request_id = hashlib.sha256(f"{hit.unit.unit_id}|{query}".encode()).hexdigest()[:24]
        attachment = enrich_visual_region(
            self._gateway,
            VisualEnrichmentRequest(
                request_id=request_id,
                region=hit.unit.visual_region,
                prompt=(
                    "Answer the user's question strictly from the provided visual evidence. "
                    f"Question: {query}"
                ),
                node_id=hit.unit.node_id,
                metadata={"query": query},
            ),
            logger=self._logger,
        )
        return QAResponse(
            answer=attachment.insight.summary,
            citations=(
                AnswerCitation(
                    document_id=hit.unit.document_id,
                    unit_id=hit.unit.unit_id,
                    page_span=hit.unit.page_span,
                    page_label=_page_label_for_span(hit.unit.page_span),
                    node_id=hit.unit.node_id,
                    quote=attachment.insight.summary,
                    asset_path=hit.unit.asset_path or hit.unit.page_render_path,
                ),
            ),
            retrieval_hits=(hit,),
            answer_mode="live_multimodal_enrichment",
            answer_strategy="live_multimodal_enrichment",
        )

    def _resolve_document_description(self, document_id: str) -> DocumentDescription | None:
        if (
            self._document_description is not None
            and self._document_description.document_id == document_id
        ):
            return self._document_description
        if self._description_resolver is None:
            return None
        return self._description_resolver(document_id)

    def _document_summary_response(
        self,
        *,
        corpus: RetrievalCorpus,
        query: str,
    ) -> QAResponse:
        description = self._resolve_document_description(corpus.document_id)
        if description is not None:
            return QAResponse(
                answer=description.description_text,
                citations=(),
                retrieval_hits=(),
                answer_mode="document_summary_description",
                answer_strategy="document_description",
            )
        fallback_summary = _document_summary_from_corpus(corpus)
        if fallback_summary is not None:
            summary_hits = tuple(
                hit
                for hit in self._retrieval_service.search(corpus=corpus, query=query, limit=5)
                if hit.unit.unit_type
                in {RetrievalUnitType.NODE_SUMMARY, RetrievalUnitType.NODE_TEXT}
            )
            return QAResponse(
                answer=fallback_summary,
                citations=tuple(
                    self._citation_for_hit(hit, query=query)
                    for hit in _distinct_hits_by_unit(summary_hits, limit=2)
                ),
                retrieval_hits=summary_hits,
                answer_mode="document_summary_fallback",
                answer_strategy="corpus_summary_fallback",
            )
        return QAResponse(
            answer="No grounded document-level summary is available in the current corpus.",
            citations=(),
            retrieval_hits=(),
            answer_mode="document_summary_unavailable",
            answer_strategy="document_summary_unavailable",
        )

    def _log_response(
        self,
        document_id: str,
        query: str,
        plan: QueryPlan,
        response: QAResponse,
    ) -> QAResponse:
        log_event(
            self._logger,
            "RetrievalQACompleted",
            document_id=document_id,
            query=query,
            query_intent=plan.query_intent.value,
            answer_mode=response.answer_mode,
            answer_strategy=response.answer_strategy,
            retrieval_hit_count=len(response.retrieval_hits),
            citation_count=len(response.citations),
        )
        return response


__all__ = [
    "QAResponse",
    "RetrievalQAService",
]
