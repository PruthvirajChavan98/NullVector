"""Answer synthesis over retrieval hits."""

from __future__ import annotations

import hashlib
import string

from nullvector.domain.common import NonEmptyStr, StrataModel
from nullvector.domain.retrieval import (
    AnswerCitation,
    RetrievalCorpus,
    RetrievalHit,
    RetrievalUnitType,
)
from nullvector.domain.tree import VisualEnrichmentRequest
from nullvector.llm.multimodal_gateway.errors import MultimodalGatewayError
from nullvector.retrieval.service import RetrievalService

_PUNCTUATION_TABLE = str.maketrans({character: " " for character in string.punctuation})


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().translate(_PUNCTUATION_TABLE).split())


def _excerpt_for_hit(hit: RetrievalHit, query: str) -> str | None:
    text = hit.unit.text
    if text is None or not text.strip():
        return None
    normalized_query_terms = tuple(term for term in _normalize_text(query).split() if term)
    best_line = ""
    best_score = -1
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        line_terms = set(_normalize_text(stripped).split())
        score = len(set(normalized_query_terms) & line_terms)
        if score > best_score:
            best_line = stripped
            best_score = score
    excerpt = best_line or text.strip().splitlines()[0]
    return excerpt[:280]


class QAResponse(StrataModel):
    """Grounded answer payload returned by retrieval QA."""

    answer: NonEmptyStr
    citations: tuple[AnswerCitation, ...] = ()
    retrieval_hits: tuple[RetrievalHit, ...] = ()
    answer_mode: NonEmptyStr


class RetrievalQAService:
    """Synthesize grounded answers from retrieval hits."""

    def __init__(
        self,
        retrieval_service: RetrievalService,
        multimodal_service: object | None = None,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._multimodal_service = multimodal_service

    def answer(
        self,
        *,
        corpus: RetrievalCorpus,
        query: str,
        limit: int = 5,
    ) -> QAResponse:
        plan = self._retrieval_service.plan(corpus=corpus, query=query)
        hits = self._retrieval_service.search(corpus=corpus, query=query, limit=limit)
        if not hits:
            return QAResponse(
                answer="No grounded evidence was found in the current corpus.",
                citations=(),
                retrieval_hits=(),
                answer_mode="no_hits",
            )

        if plan.visual_query:
            visual_hits = tuple(
                hit
                for hit in hits
                if hit.unit.unit_type in {
                    RetrievalUnitType.VISUAL,
                    RetrievalUnitType.UNRESOLVED_VISUAL,
                }
            )
            if not visual_hits:
                return QAResponse(
                    answer="No visual evidence was found for the requested scope.",
                    citations=(),
                    retrieval_hits=hits,
                    answer_mode="visual_no_hits",
                )
            top_visual = visual_hits[0]
            if top_visual.unit.text and top_visual.unit.interpretive:
                citation = self._citation_for_hit(top_visual, query=query)
                return QAResponse(
                    answer=top_visual.unit.text,
                    citations=(citation,),
                    retrieval_hits=hits,
                    answer_mode="cached_visual_attachment",
                )
            if self._multimodal_service is not None and top_visual.unit.visual_region is not None:
                try:
                    enriched = self._enrich_visual_hit(hit=top_visual, query=query)
                except MultimodalGatewayError:
                    enriched = None
                except Exception:
                    enriched = None
                if enriched is not None:
                    return enriched
            return self._visual_interpretation_unavailable_response(
                hit=top_visual,
                query=query,
                retrieval_hits=hits,
            )

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
        chosen_hit = authoritative_hits[0] if authoritative_hits else hits[0]
        answer = (
            _excerpt_for_hit(chosen_hit, query)
            or chosen_hit.unit.title
            or "Grounded evidence was found, but no answerable text excerpt is available."
        )
        citations_source = authoritative_hits[:3] if authoritative_hits else hits[:1]
        return QAResponse(
            answer=answer,
            citations=tuple(self._citation_for_hit(hit, query=query) for hit in citations_source),
            retrieval_hits=hits,
            answer_mode="authoritative_text"
            if authoritative_hits
            else "interpretive_fallback",
        )

    def _citation_for_hit(self, hit: RetrievalHit, *, query: str) -> AnswerCitation:
        return AnswerCitation(
            document_id=hit.unit.document_id,
            unit_id=hit.unit.unit_id,
            page_span=hit.unit.page_span,
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
        )

    def _enrich_visual_hit(self, *, hit: RetrievalHit, query: str) -> QAResponse | None:
        if self._multimodal_service is None or hit.unit.visual_region is None:
            return None
        enrich = getattr(self._multimodal_service, "enrich", None)
        if not callable(enrich):
            return None
        request_id = hashlib.sha256(f"{hit.unit.unit_id}|{query}".encode()).hexdigest()[:24]
        attachment = enrich(
            VisualEnrichmentRequest(
                request_id=request_id,
                region=hit.unit.visual_region,
                prompt=(
                    "Answer the user's question strictly from the provided visual evidence. "
                    f"Question: {query}"
                ),
                node_id=hit.unit.node_id,
                metadata={"query": query},
            )
        )
        return QAResponse(
            answer=attachment.insight.summary,
            citations=(
                AnswerCitation(
                    document_id=hit.unit.document_id,
                    unit_id=hit.unit.unit_id,
                    page_span=hit.unit.page_span,
                    node_id=hit.unit.node_id,
                    quote=attachment.insight.summary,
                    asset_path=hit.unit.asset_path or hit.unit.page_render_path,
                ),
            ),
            retrieval_hits=(hit,),
            answer_mode="live_multimodal_enrichment",
        )


__all__ = [
    "QAResponse",
    "RetrievalQAService",
]
