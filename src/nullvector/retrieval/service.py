"""Retrieval orchestration over a persisted corpus."""

from __future__ import annotations

from logging import Logger

from nullvector.domain.common import PageSpan
from nullvector.domain.retrieval import (
    QueryPlan,
    RetrievalCorpus,
    RetrievalEvidence,
    RetrievalHit,
    RetrievalUnitType,
)
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.retrieval.index import InMemoryRetrievalIndex, PostgresRetrievalIndex
from nullvector.retrieval.planner import QueryPlanner
from nullvector.retrieval.rank import RetrievalRanker
from nullvector.storage import StorageConfig, build_document_store
from nullvector.storage.config import StorageBackend


def _intersects(unit: RetrievalEvidence, page_span: PageSpan) -> bool:
    return not (
        unit.page_span.end_page < page_span.start_page
        or page_span.end_page < unit.page_span.start_page
    )


def _dedupe_units(units: tuple[RetrievalEvidence, ...]) -> tuple[RetrievalEvidence, ...]:
    deduped: list[RetrievalEvidence] = []
    seen: set[str] = set()
    for unit in units:
        if unit.unit_id in seen:
            continue
        seen.add(unit.unit_id)
        deduped.append(unit)
    return tuple(deduped)


class RetrievalService:
    """Query planning, filtering, widening, and ranking over one corpus."""

    def __init__(
        self,
        planner: QueryPlanner,
        ranker: RetrievalRanker,
        *,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._planner = planner
        self._ranker = ranker
        self._logger = resolve_runtime_logger(logger)
        self._storage = storage

    def plan(self, *, corpus: RetrievalCorpus, query: str) -> QueryPlan:
        plan = self._planner.plan(query)
        if plan.page_filter is None and "last page" in plan.normalized_query:
            max_page = max((unit.page_span.end_page for unit in corpus.units), default=0)
            return plan.model_copy(
                update={"page_filter": PageSpan(start_page=max_page, end_page=max_page)}
            )
        return plan

    def search(
        self,
        *,
        corpus: RetrievalCorpus | None = None,
        document_id: str | None = None,
        query: str,
        limit: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        if corpus is None and document_id is None:
            msg = "retrieval search requires either a corpus or a document_id"
            raise ValueError(msg)
        resolved_document_id = corpus.document_id if corpus is not None else document_id or ""
        log_event(
            self._logger,
            "RetrievalSearchStarted",
            document_id=resolved_document_id,
            query=query,
            limit=limit,
            using_loaded_corpus=corpus is not None,
        )
        if corpus is not None:
            plan = self.plan(corpus=corpus, query=query)
        else:
            plan = self._planner.plan(query)
        index = self._index(corpus=corpus, document_id=document_id)
        candidates = index.filter_units(plan)
        used_widening = False
        if not candidates:
            if corpus is None:
                log_event(
                    self._logger,
                    "RetrievalSearchCompleted",
                    document_id=resolved_document_id,
                    query=query,
                    limit=limit,
                    candidate_count=0,
                    hit_count=0,
                    used_widening=False,
                )
                return ()
            used_widening = True
            candidates = self._widen_candidates(corpus=corpus, plan=plan)
        if not candidates:
            log_event(
                self._logger,
                "RetrievalSearchCompleted",
                document_id=resolved_document_id,
                query=query,
                limit=limit,
                candidate_count=0,
                hit_count=0,
                used_widening=used_widening,
            )
            return ()
        ranked = self._ranker.rank(query=query, plan=plan, candidates=candidates)
        hits = ranked[:limit]
        log_event(
            self._logger,
            "RetrievalSearchCompleted",
            document_id=resolved_document_id,
            query=query,
            limit=limit,
            candidate_count=len(candidates),
            hit_count=len(hits),
            used_widening=used_widening,
        )
        return hits

    def _index(
        self,
        *,
        corpus: RetrievalCorpus | None,
        document_id: str | None,
    ) -> InMemoryRetrievalIndex | PostgresRetrievalIndex:
        if corpus is not None:
            return InMemoryRetrievalIndex(corpus)
        if document_id is None:
            msg = "retrieval search requires document_id when corpus is not provided"
            raise ValueError(msg)
        store = build_document_store(
            self._storage,
            default_filesystem_root=".",
        )
        if store.backend is StorageBackend.POSTGRES:
            return PostgresRetrievalIndex(store, document_id=document_id)
        msg = "filesystem retrieval search requires a loaded retrieval corpus"
        raise ValueError(msg)

    def _widen_candidates(
        self,
        *,
        corpus: RetrievalCorpus,
        plan: QueryPlan,
    ) -> tuple[RetrievalEvidence, ...]:
        if plan.visual_query:
            if plan.page_filter is not None:
                same_page_visual = tuple(
                    unit
                    for unit in corpus.units
                    if _intersects(unit, plan.page_filter)
                    and unit.unit_type
                    in {
                        RetrievalUnitType.VISUAL,
                        RetrievalUnitType.UNRESOLVED_VISUAL,
                    }
                )
                if same_page_visual:
                    return _dedupe_units(same_page_visual)

                same_page_units = tuple(
                    unit
                    for unit in corpus.units
                    if _intersects(unit, plan.page_filter)
                    and unit.unit_type
                    in {
                        RetrievalUnitType.PAGE_TEXT,
                        RetrievalUnitType.TABLE,
                        RetrievalUnitType.UNASSIGNED_SPAN,
                    }
                )
                return _dedupe_units(same_page_units)

            visual_units = tuple(
                unit
                for unit in corpus.units
                if unit.unit_type
                in {
                    RetrievalUnitType.VISUAL,
                    RetrievalUnitType.UNRESOLVED_VISUAL,
                }
            )
            return _dedupe_units(visual_units)

        if plan.table_query:
            if plan.page_filter is not None:
                same_page_tables = tuple(
                    unit
                    for unit in corpus.units
                    if _intersects(unit, plan.page_filter)
                    and unit.unit_type is RetrievalUnitType.TABLE
                )
                if same_page_tables:
                    return _dedupe_units(same_page_tables)
                same_page_text = tuple(
                    unit
                    for unit in corpus.units
                    if _intersects(unit, plan.page_filter)
                    and unit.unit_type
                    in {
                        RetrievalUnitType.PAGE_TEXT,
                        RetrievalUnitType.UNASSIGNED_SPAN,
                    }
                )
                if same_page_text:
                    return _dedupe_units(same_page_text)
            return _dedupe_units(
                tuple(unit for unit in corpus.units if unit.unit_type is RetrievalUnitType.TABLE)
            )

        if plan.page_filter is not None:
            same_page_units = tuple(
                unit for unit in corpus.units if _intersects(unit, plan.page_filter)
            )
            if same_page_units:
                return _dedupe_units(same_page_units)

        if plan.unit_types:
            type_only_units = tuple(
                unit for unit in corpus.units if unit.unit_type in set(plan.unit_types)
            )
            if type_only_units:
                return _dedupe_units(type_only_units)

        return corpus.units


__all__ = ["RetrievalService"]
