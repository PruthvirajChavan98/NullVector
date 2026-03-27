"""Collection-scoped description selection before document retrieval."""

from __future__ import annotations

from logging import Logger

from nullvector._text import normalize_text, tokenize
from nullvector.domain.document_selection import (
    DescriptionSelectionCandidate,
    DescriptionSelectionMode,
    DescriptionSelectionRequest,
    DescriptionSelectionResponse,
    DocumentDescriptionRecord,
)
from nullvector.llm.prompts.description_selection import (
    DescriptionSelectionPromptResponse,
    build_description_selection_messages,
)
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest
from nullvector.observability.logging import log_event, resolve_runtime_logger
from nullvector.retrieval._selection_artifacts import (
    selection_artifact_path,
    selection_artifact_root,
)
from nullvector.storage import StorageConfig, build_document_store

_DESCRIPTION_SHARD_SIZE = 25
_EXACT_SUBSTRING_BOOST = 1.0


def _description_sort_key(record: DocumentDescriptionRecord) -> tuple[str, str]:
    return (record.display_name.casefold(), record.document_id)


def _candidate_sort_key(
    candidate: DescriptionSelectionCandidate,
    records_by_id: dict[str, DocumentDescriptionRecord],
) -> tuple[float, str, str]:
    record = records_by_id[candidate.document_id]
    return (-candidate.score, record.display_name.casefold(), record.document_id)


def _iter_shards(
    records: tuple[DocumentDescriptionRecord, ...],
    *,
    shard_size: int,
) -> tuple[tuple[DocumentDescriptionRecord, ...], ...]:
    return tuple(
        records[index : index + shard_size] for index in range(0, len(records), shard_size)
    )


def _fallback_candidate(
    record: DocumentDescriptionRecord,
    *,
    query_tokens: tuple[str, ...],
    normalized_query: str,
) -> DescriptionSelectionCandidate:
    candidate_text = normalize_text(f"{record.display_name} {record.description_text}")
    candidate_tokens = frozenset(tokenize(candidate_text))
    matched_tokens = tuple(token for token in query_tokens if token in candidate_tokens)
    overlap_score = float(len(matched_tokens)) / float(len(query_tokens)) if query_tokens else 0.0
    substring_boost = (
        _EXACT_SUBSTRING_BOOST if normalized_query and normalized_query in candidate_text else 0.0
    )
    return DescriptionSelectionCandidate(
        document_id=record.document_id,
        score=overlap_score + substring_boost,
        reason=f"matched {len(matched_tokens)}/{len(query_tokens)} query tokens in description",
    )


def _fallback_candidates(
    records: tuple[DocumentDescriptionRecord, ...],
    *,
    query: str,
    limit: int,
) -> tuple[DescriptionSelectionCandidate, ...]:
    ordered_records = tuple(sorted(records, key=_description_sort_key))
    query_tokens = tokenize(query)
    normalized_query = normalize_text(query)
    scored = tuple(
        _fallback_candidate(
            record,
            query_tokens=query_tokens,
            normalized_query=normalized_query,
        )
        for record in ordered_records
    )
    records_by_id = {record.document_id: record for record in ordered_records}
    positive = tuple(candidate for candidate in scored if candidate.score > 0.0)
    zero_score = tuple(candidate for candidate in scored if candidate.score == 0.0)
    ranked_positive = tuple(
        sorted(
            positive,
            key=lambda candidate: _candidate_sort_key(candidate, records_by_id),
        )
    )
    if len(ranked_positive) >= limit:
        return ranked_positive[:limit]
    remaining = max(limit - len(ranked_positive), 0)
    return ranked_positive + zero_score[:remaining]


def _gateway_candidates_for_shard(
    shard: tuple[DocumentDescriptionRecord, ...],
    *,
    query: str,
    gateway: StructuredLLMGateway,
) -> tuple[DescriptionSelectionCandidate, ...]:
    gateway_result = gateway.invoke(
        GatewayRequest[DescriptionSelectionPromptResponse](
            operation_name="description_selection",
            messages=build_description_selection_messages(
                query=query,
                descriptions=tuple(
                    {
                        "document_id": record.document_id,
                        "display_name": record.display_name,
                        "description_text": record.description_text,
                    }
                    for record in shard
                ),
            ),
            response_model=DescriptionSelectionPromptResponse,
            max_output_tokens=450,
            metadata={
                "query": query,
                "candidate_count": len(shard),
            },
        )
    )
    shard_ids = {record.document_id for record in shard}
    invalid_document_ids = tuple(
        sorted(
            {
                candidate.document_id
                for candidate in gateway_result.output.candidates
                if candidate.document_id not in shard_ids
            }
        )
    )
    if invalid_document_ids:
        msg = (
            "description_selection returned document_ids outside the provided shard: "
            f"{invalid_document_ids}"
        )
        raise ValueError(msg)
    return tuple(
        DescriptionSelectionCandidate(
            document_id=candidate.document_id,
            score=float(candidate.relevance_score),
            reason=candidate.reason,
        )
        for candidate in gateway_result.output.candidates
    )


def _merge_gateway_candidates(
    candidates: tuple[DescriptionSelectionCandidate, ...],
    *,
    records_by_id: dict[str, DocumentDescriptionRecord],
    limit: int,
) -> tuple[DescriptionSelectionCandidate, ...]:
    best_by_document_id: dict[str, DescriptionSelectionCandidate] = {}
    for candidate in candidates:
        existing = best_by_document_id.get(candidate.document_id)
        if existing is None or (
            candidate.score,
            candidate.reason,
        ) > (
            existing.score,
            existing.reason,
        ):
            best_by_document_id[candidate.document_id] = candidate
    merged = tuple(
        sorted(
            best_by_document_id.values(),
            key=lambda candidate: _candidate_sort_key(candidate, records_by_id),
        )
    )
    return merged[:limit]


class DescriptionSelectionService:
    """Execute description-based document selection before retrieval."""

    def __init__(
        self,
        *,
        logger: Logger | None = None,
        storage: StorageConfig | None = None,
    ) -> None:
        self._logger = resolve_runtime_logger(logger)
        self._storage = storage

    def select(
        self,
        request: DescriptionSelectionRequest,
        *,
        gateway: StructuredLLMGateway | None = None,
    ) -> DescriptionSelectionResponse:
        log_event(
            self._logger,
            "DescriptionSelectionStarted",
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            query=request.query,
            description_count=len(request.descriptions),
        )
        artifact_root = selection_artifact_root(
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            artifact_root=request.artifact_root,
            storage=self._storage,
        )
        store = build_document_store(self._storage, default_filesystem_root=".")
        index_records = tuple(sorted(request.descriptions, key=_description_sort_key))
        records_by_id = {record.document_id: record for record in index_records}

        description_index_path = store.put_jsonl_artifact(
            run_type="document_selection",
            run_id=request.selection_run_id,
            document_id=request.collection_id,
            artifact_kind="document_selection",
            artifact_path=selection_artifact_path(artifact_root, "description-index.jsonl"),
            payloads=tuple(record.model_dump(mode="json") for record in index_records),
        )

        if gateway is None:
            candidates = _fallback_candidates(
                index_records,
                query=request.query,
                limit=request.limit,
            )
            selection_mode = DescriptionSelectionMode.DETERMINISTIC_FALLBACK
        else:
            shard_candidates: list[DescriptionSelectionCandidate] = []
            for shard in _iter_shards(index_records, shard_size=_DESCRIPTION_SHARD_SIZE):
                shard_candidates.extend(
                    _gateway_candidates_for_shard(
                        shard,
                        query=request.query,
                        gateway=gateway,
                    )
                )
            candidates = _merge_gateway_candidates(
                tuple(shard_candidates),
                records_by_id=records_by_id,
                limit=request.limit,
            )
            selection_mode = DescriptionSelectionMode.LLM

        selection_results_path = store.put_json_artifact(
            run_type="document_selection",
            run_id=request.selection_run_id,
            document_id=request.collection_id,
            artifact_kind="document_selection",
            artifact_path=selection_artifact_path(
                artifact_root,
                "description-selection-results.json",
            ),
            payload={
                "collection_id": request.collection_id,
                "selection_run_id": request.selection_run_id,
                "selection_mode": selection_mode.value,
                "query": request.query,
                "candidate_count": len(candidates),
                "candidates": tuple(candidate.model_dump(mode="json") for candidate in candidates),
            },
        )
        response = DescriptionSelectionResponse(
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            candidates=candidates,
            selection_mode=selection_mode,
            artifact_root=artifact_root,
            description_index_path=description_index_path,
            selection_results_path=selection_results_path,
        )
        log_event(
            self._logger,
            "DescriptionSelectionCompleted",
            collection_id=request.collection_id,
            selection_run_id=request.selection_run_id,
            query=request.query,
            description_count=len(index_records),
            selection_mode=selection_mode.value,
            candidate_count=len(candidates),
            results_path=selection_results_path,
        )
        return response


__all__ = [
    "DescriptionSelectionService",
]
