"""Derived serving-tree compaction over persisted canonical tree artifacts."""

from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from nullvector._hierarchy import document_order_key as hierarchy_document_order_key
from nullvector.domain.common import PageSpan
from nullvector.domain.tree import (
    CompactedNodeMapping,
    CompactedTreeManifest,
    CompactedTreeNode,
    HierarchyNode,
    NodeCard,
    NodeSummary,
    TreeBuildManifest,
    TreeCompactionRequest,
)
from nullvector.storage import StorageConfig, build_document_store, reservation_artifact_root
from nullvector.storage._serialization import (
    canonical_json_text,
    is_postgres_ref,
    run_identity_matches,
    settings_digest,
)
from nullvector.storage.protocol import DocumentStore

_PATHOLOGICAL_MULTIPLIER = 2
_MERGED_SUMMARY_LIMIT = 3


@dataclass(slots=True)
class _SiblingSegment:
    """One contiguous sibling segment used during pathological-width collapsing."""

    segment_id: int
    child_ids: tuple[str, ...]
    total_score: float
    start_index: int
    prev_id: int | None = None
    next_id: int | None = None
    active: bool = True


def _normalize_artifact_ref(ref: str) -> str:
    if is_postgres_ref(ref):
        return ref
    return str(Path(ref).resolve())


def _load_tree_manifest(
    store: DocumentStore,
    ref: str,
) -> TreeBuildManifest:
    return TreeBuildManifest.model_validate_json(canonical_json_text(store.read_json_artifact(ref)))


def _load_committed_nodes(
    store: DocumentStore,
    manifest: TreeBuildManifest,
) -> tuple[HierarchyNode, ...]:
    if manifest.committed_hierarchy_path is None:
        msg = "tree compaction requires committed hierarchy nodes"
        raise ValueError(msg)
    payload = cast(
        list[dict[str, Any]],
        store.read_json_artifact(manifest.committed_hierarchy_path),
    )
    return tuple(HierarchyNode.model_validate_json(json.dumps(item)) for item in payload)


def _load_node_cards(
    store: DocumentStore,
    manifest: TreeBuildManifest,
) -> tuple[NodeCard, ...]:
    if manifest.node_cards_path is None:
        msg = "tree compaction requires node cards"
        raise ValueError(msg)
    payload = cast(list[dict[str, Any]], store.read_json_artifact(manifest.node_cards_path))
    return tuple(NodeCard.model_validate_json(json.dumps(item)) for item in payload)


def _load_node_summaries(
    store: DocumentStore,
    manifest: TreeBuildManifest,
) -> tuple[NodeSummary, ...]:
    if manifest.node_summaries_path is None:
        return ()
    payload = cast(list[dict[str, Any]], store.read_json_artifact(manifest.node_summaries_path))
    return tuple(NodeSummary.model_validate_json(json.dumps(item)) for item in payload)


def _document_order_key(
    node_id: str,
    *,
    nodes_by_id: dict[str, HierarchyNode],
) -> tuple[int, int, int, tuple[str, ...], str]:
    node = nodes_by_id[node_id]
    return hierarchy_document_order_key(
        page_span=node.page_span,
        level=node.level,
        path=node.path,
        identifier=node_id,
    )


def _page_width(node: HierarchyNode) -> int:
    return node.page_span.end_page - node.page_span.start_page + 1


def _summary_text_for_node(
    node_id: str,
    *,
    cards_by_id: dict[str, NodeCard],
    summaries_by_id: dict[str, NodeSummary],
) -> str | None:
    summary = summaries_by_id.get(node_id)
    if summary is not None:
        return summary.summary
    card = cards_by_id.get(node_id)
    return card.summary if card is not None else None


def _importance_score(
    node_id: str,
    *,
    nodes_by_id: dict[str, HierarchyNode],
    children_by_parent: dict[str | None, tuple[str, ...]],
    cards_by_id: dict[str, NodeCard],
    summaries_by_id: dict[str, NodeSummary],
) -> float:
    node = nodes_by_id[node_id]
    score = float(_page_width(node))
    if _summary_text_for_node(node_id, cards_by_id=cards_by_id, summaries_by_id=summaries_by_id):
        score += 4.0
    if children_by_parent.get(node_id):
        score += 3.0
    score += 1.0 / float(node.level)
    return score


def _is_high_signal(
    node_id: str,
    *,
    nodes_by_id: dict[str, HierarchyNode],
    children_by_parent: dict[str | None, tuple[str, ...]],
    cards_by_id: dict[str, NodeCard],
    summaries_by_id: dict[str, NodeSummary],
) -> bool:
    return (
        _summary_text_for_node(node_id, cards_by_id=cards_by_id, summaries_by_id=summaries_by_id)
        is not None
        or bool(children_by_parent.get(node_id))
        or _page_width(nodes_by_id[node_id]) > 1
    )


def _build_children_by_parent(
    nodes: tuple[HierarchyNode, ...],
) -> dict[str | None, tuple[str, ...]]:
    nodes_by_id = {node.node_id: node for node in nodes}
    raw: dict[str | None, list[str]] = {}
    for node in nodes:
        raw.setdefault(node.parent_id, []).append(node.node_id)
    return {
        parent_id: tuple(
            sorted(
                child_ids,
                key=lambda node_id: _document_order_key(node_id, nodes_by_id=nodes_by_id),
            )
        )
        for parent_id, child_ids in raw.items()
    }


def _root_node_ids(
    *,
    nodes_by_id: dict[str, HierarchyNode],
    children_by_parent: dict[str | None, tuple[str, ...]],
) -> tuple[str, ...]:
    explicit_roots = children_by_parent.get(None, ())
    if explicit_roots:
        return explicit_roots
    if not nodes_by_id:
        return ()
    min_level = min(node.level for node in nodes_by_id.values())
    return tuple(
        node_id
        for node_id, _node in sorted(
            ((node_id, node) for node_id, node in nodes_by_id.items() if node.level == min_level),
            key=lambda item: _document_order_key(item[0], nodes_by_id=nodes_by_id),
        )
    )


def _subtree_node_ids(
    node_id: str,
    *,
    children_by_parent: dict[str | None, tuple[str, ...]],
    cache: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    if node_id in cache:
        return cache[node_id]
    stack: list[tuple[str, bool]] = [(node_id, False)]
    while stack:
        current_node_id, expanded = stack.pop()
        if current_node_id in cache:
            continue
        if expanded:
            ordered: list[str] = [current_node_id]
            for child_id in children_by_parent.get(current_node_id, ()):
                ordered.extend(cache[child_id])
            cache[current_node_id] = tuple(ordered)
            continue
        stack.append((current_node_id, True))
        for child_id in reversed(children_by_parent.get(current_node_id, ())):
            if child_id not in cache:
                stack.append((child_id, False))
    return cache[node_id]


def _merged_title(
    canonical_node_ids: tuple[str, ...],
    *,
    nodes_by_id: dict[str, HierarchyNode],
) -> str:
    first_title = nodes_by_id[canonical_node_ids[0]].title
    extra_count = len(canonical_node_ids) - 1
    if extra_count <= 0:
        return first_title
    return f"{first_title} (+{extra_count})"


def _merged_summary_text(
    canonical_node_ids: tuple[str, ...],
    *,
    cards_by_id: dict[str, NodeCard],
    summaries_by_id: dict[str, NodeSummary],
) -> str | None:
    fragments: list[str] = []
    seen: set[str] = set()
    for node_id in canonical_node_ids:
        summary_text = _summary_text_for_node(
            node_id,
            cards_by_id=cards_by_id,
            summaries_by_id=summaries_by_id,
        )
        if summary_text is None:
            continue
        normalized = " ".join(summary_text.split()).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        fragments.append(normalized)
        if len(fragments) >= _MERGED_SUMMARY_LIMIT:
            break
    if not fragments:
        return None
    return " ".join(fragments)


def _merged_page_span(
    canonical_node_ids: tuple[str, ...],
    *,
    nodes_by_id: dict[str, HierarchyNode],
) -> PageSpan:
    first = nodes_by_id[canonical_node_ids[0]].page_span
    start_page = first.start_page
    end_page = first.end_page
    for node_id in canonical_node_ids[1:]:
        page_span = nodes_by_id[node_id].page_span
        start_page = min(start_page, page_span.start_page)
        end_page = max(end_page, page_span.end_page)
    return PageSpan(start_page=start_page, end_page=end_page)


def _mild_overflow_segments(
    child_ids: tuple[str, ...],
    *,
    nodes_by_id: dict[str, HierarchyNode],
    children_by_parent: dict[str | None, tuple[str, ...]],
    cards_by_id: dict[str, NodeCard],
    summaries_by_id: dict[str, NodeSummary],
) -> tuple[tuple[tuple[str, ...], bool], ...]:
    high_signal_ids = {
        child_id
        for child_id in child_ids
        if _is_high_signal(
            child_id,
            nodes_by_id=nodes_by_id,
            children_by_parent=children_by_parent,
            cards_by_id=cards_by_id,
            summaries_by_id=summaries_by_id,
        )
    }
    if not high_signal_ids:
        return tuple(((child_id,), False) for child_id in child_ids)

    segments: list[tuple[tuple[str, ...], bool]] = []
    buffered: list[str] = []
    for child_id in child_ids:
        if child_id in high_signal_ids:
            if buffered:
                segments.append((tuple(buffered), True))
                buffered.clear()
            segments.append(((child_id,), False))
            continue
        buffered.append(child_id)
    if buffered:
        segments.append((tuple(buffered), True))
    return tuple(segments)


def _pathological_segments(
    child_ids: tuple[str, ...],
    *,
    max_children_per_node: int,
    nodes_by_id: dict[str, HierarchyNode],
    children_by_parent: dict[str | None, tuple[str, ...]],
    cards_by_id: dict[str, NodeCard],
    summaries_by_id: dict[str, NodeSummary],
) -> tuple[tuple[tuple[str, ...], bool], ...]:
    importance_by_id = {
        child_id: _importance_score(
            child_id,
            nodes_by_id=nodes_by_id,
            children_by_parent=children_by_parent,
            cards_by_id=cards_by_id,
            summaries_by_id=summaries_by_id,
        )
        for child_id in child_ids
    }
    segments: dict[int, _SiblingSegment] = {}
    heap: list[tuple[float, int, int, int]] = []
    next_segment_id = 0
    head_id: int | None = None

    def push_merge_cost(left_id: int, right_id: int) -> None:
        left = segments[left_id]
        right = segments[right_id]
        merged_count = len(left.child_ids) + len(right.child_ids)
        merged_score = (left.total_score + right.total_score) / float(merged_count)
        heapq.heappush(heap, (merged_score, left.start_index, left_id, right_id))

    for index, child_id in enumerate(child_ids):
        segment = _SiblingSegment(
            segment_id=next_segment_id,
            child_ids=(child_id,),
            total_score=importance_by_id[child_id],
            start_index=index,
            prev_id=next_segment_id - 1 if next_segment_id > 0 else None,
        )
        segments[segment.segment_id] = segment
        if segment.prev_id is not None:
            segments[segment.prev_id].next_id = segment.segment_id
            push_merge_cost(segment.prev_id, segment.segment_id)
        if head_id is None:
            head_id = segment.segment_id
        next_segment_id += 1

    active_segments = len(child_ids)
    while active_segments > max_children_per_node:
        _merge_score, _start_index, left_id, right_id = heapq.heappop(heap)
        left = segments[left_id]
        right = segments[right_id]
        if not left.active or not right.active or left.next_id != right.segment_id:
            continue
        merged = _SiblingSegment(
            segment_id=next_segment_id,
            child_ids=left.child_ids + right.child_ids,
            total_score=left.total_score + right.total_score,
            start_index=left.start_index,
            prev_id=left.prev_id,
            next_id=right.next_id,
        )
        next_segment_id += 1
        segments[merged.segment_id] = merged
        left.active = False
        right.active = False
        if merged.prev_id is not None:
            segments[merged.prev_id].next_id = merged.segment_id
            push_merge_cost(merged.prev_id, merged.segment_id)
        else:
            head_id = merged.segment_id
        if merged.next_id is not None:
            segments[merged.next_id].prev_id = merged.segment_id
            push_merge_cost(merged.segment_id, merged.next_id)
        active_segments -= 1

    ordered_segments: list[tuple[tuple[str, ...], bool]] = []
    current_id = head_id
    while current_id is not None:
        segment = segments[current_id]
        if segment.active:
            ordered_segments.append((segment.child_ids, len(segment.child_ids) > 1))
        current_id = segment.next_id
    return tuple(ordered_segments)


def _child_segments(
    child_ids: tuple[str, ...],
    *,
    max_children_per_node: int,
    nodes_by_id: dict[str, HierarchyNode],
    children_by_parent: dict[str | None, tuple[str, ...]],
    cards_by_id: dict[str, NodeCard],
    summaries_by_id: dict[str, NodeSummary],
) -> tuple[tuple[tuple[str, ...], bool], ...]:
    if len(child_ids) <= max_children_per_node:
        return tuple(((child_id,), False) for child_id in child_ids)
    if len(child_ids) <= (max_children_per_node * _PATHOLOGICAL_MULTIPLIER):
        return _mild_overflow_segments(
            child_ids,
            nodes_by_id=nodes_by_id,
            children_by_parent=children_by_parent,
            cards_by_id=cards_by_id,
            summaries_by_id=summaries_by_id,
        )
    return _pathological_segments(
        child_ids,
        max_children_per_node=max_children_per_node,
        nodes_by_id=nodes_by_id,
        children_by_parent=children_by_parent,
        cards_by_id=cards_by_id,
        summaries_by_id=summaries_by_id,
    )


def _merged_serving_node(
    *,
    parent_id: str,
    parent_path: tuple[str, ...],
    parent_level: int,
    child_segment: tuple[str, ...],
    segment_index: int,
    nodes_by_id: dict[str, HierarchyNode],
    children_by_parent: dict[str | None, tuple[str, ...]],
    cards_by_id: dict[str, NodeCard],
    summaries_by_id: dict[str, NodeSummary],
    require_summaries: bool,
    subtree_cache: dict[str, tuple[str, ...]],
) -> CompactedTreeNode:
    canonical_node_ids = tuple(
        node_id
        for child_id in child_segment
        for node_id in _subtree_node_ids(
            child_id,
            children_by_parent=children_by_parent,
            cache=subtree_cache,
        )
    )
    summary_text = _merged_summary_text(
        canonical_node_ids,
        cards_by_id=cards_by_id,
        summaries_by_id=summaries_by_id,
    )
    if summary_text is None and require_summaries:
        msg = (
            "tree compaction requires summaries for merged serving nodes; "
            f"missing summaries under canonical ids {canonical_node_ids}"
        )
        raise ValueError(msg)
    title = _merged_title(canonical_node_ids, nodes_by_id=nodes_by_id)
    page_span = _merged_page_span(canonical_node_ids, nodes_by_id=nodes_by_id)
    serving_node_id = f"{parent_id}::compact::{segment_index:02d}"
    node = CompactedTreeNode(
        serving_node_id=serving_node_id,
        title=title,
        level=parent_level + 1,
        path=(*parent_path, title),
        page_span=page_span,
        summary_text=summary_text,
        child_serving_node_ids=(),
        canonical_node_ids=canonical_node_ids,
    )
    return node


def _postorder_node_ids(nodes_by_id: dict[str, HierarchyNode]) -> tuple[str, ...]:
    return tuple(
        node_id
        for node_id, _node in sorted(
            nodes_by_id.items(),
            key=lambda item: (
                -item[1].level,
                _document_order_key(item[0], nodes_by_id=nodes_by_id),
            ),
        )
    )


def _flatten_serving_nodes(
    *,
    root_ids: tuple[str, ...],
    serving_nodes_by_id: dict[str, CompactedTreeNode],
) -> tuple[CompactedTreeNode, ...]:
    ordered: list[CompactedTreeNode] = []
    stack = list(reversed(root_ids))
    seen: set[str] = set()
    while stack:
        serving_node_id = stack.pop()
        if serving_node_id in seen:
            continue
        seen.add(serving_node_id)
        node = serving_nodes_by_id[serving_node_id]
        ordered.append(node)
        stack.extend(reversed(node.child_serving_node_ids))
    return tuple(ordered)


def _build_compacted_tree(
    *,
    nodes: tuple[HierarchyNode, ...],
    node_cards: tuple[NodeCard, ...],
    node_summaries: tuple[NodeSummary, ...],
    request: TreeCompactionRequest,
) -> tuple[CompactedTreeNode, ...]:
    nodes_by_id = {node.node_id: node for node in nodes}
    cards_by_id = {node_card.node_id: node_card for node_card in node_cards}
    summaries_by_id = {summary.node_id: summary for summary in node_summaries}
    children_by_parent = _build_children_by_parent(nodes)
    subtree_cache: dict[str, tuple[str, ...]] = {}
    serving_nodes_by_id: dict[str, CompactedTreeNode] = {}

    for node_id in _postorder_node_ids(nodes_by_id):
        node = nodes_by_id[node_id]
        card = cards_by_id.get(node_id)
        child_ids = children_by_parent.get(node_id, ())
        child_segments = _child_segments(
            child_ids,
            max_children_per_node=request.settings.max_children_per_node,
            nodes_by_id=nodes_by_id,
            children_by_parent=children_by_parent,
            cards_by_id=cards_by_id,
            summaries_by_id=summaries_by_id,
        )

        serving_child_ids: list[str] = []
        for segment_index, (child_segment, collapsed) in enumerate(child_segments, start=1):
            if not collapsed and len(child_segment) == 1 and child_segment[0] in child_ids:
                serving_child_ids.append(child_segment[0])
                continue
            merged_node = _merged_serving_node(
                parent_id=node_id,
                parent_path=node.path,
                parent_level=node.level,
                child_segment=child_segment,
                segment_index=segment_index,
                nodes_by_id=nodes_by_id,
                children_by_parent=children_by_parent,
                cards_by_id=cards_by_id,
                summaries_by_id=summaries_by_id,
                require_summaries=request.settings.require_summaries,
                subtree_cache=subtree_cache,
            )
            serving_nodes_by_id[merged_node.serving_node_id] = merged_node
            serving_child_ids.append(merged_node.serving_node_id)

        serving_nodes_by_id[node_id] = CompactedTreeNode(
            serving_node_id=node_id,
            title=card.title if card is not None else node.title,
            level=card.level if card is not None else node.level,
            path=card.path if card is not None else node.path,
            page_span=card.page_span if card is not None else node.page_span,
            summary_text=_summary_text_for_node(
                node_id,
                cards_by_id=cards_by_id,
                summaries_by_id=summaries_by_id,
            ),
            child_serving_node_ids=tuple(serving_child_ids),
            canonical_node_ids=(node_id,),
        )

    root_ids = _root_node_ids(nodes_by_id=nodes_by_id, children_by_parent=children_by_parent)
    return _flatten_serving_nodes(
        root_ids=root_ids,
        serving_nodes_by_id=serving_nodes_by_id,
    )


def _build_node_mappings(
    compacted_nodes: tuple[CompactedTreeNode, ...],
) -> tuple[CompactedNodeMapping, ...]:
    return tuple(
        CompactedNodeMapping(
            serving_node_id=node.serving_node_id,
            canonical_node_ids=node.canonical_node_ids,
        )
        for node in compacted_nodes
    )


def _default_compaction_root(
    *,
    request: TreeCompactionRequest,
    tree_manifest_ref: str,
) -> str:
    if is_postgres_ref(tree_manifest_ref):
        return f"tree-compaction/{request.compaction_run_id}"
    return str(Path(tree_manifest_ref).resolve().parent / "compaction" / request.compaction_run_id)


class TreeCompactionService:
    """Build a serving-oriented compacted tree from canonical tree artifacts."""

    def __init__(self, *, storage: StorageConfig | None = None) -> None:
        self._storage = storage

    def compact(
        self,
        request: TreeCompactionRequest,
    ) -> CompactedTreeManifest:
        input_store = build_document_store(self._storage, default_filesystem_root=".")
        tree_manifest_ref = _normalize_artifact_ref(request.tree_manifest_path)
        tree_manifest = _load_tree_manifest(input_store, tree_manifest_ref)
        nodes = _load_committed_nodes(input_store, tree_manifest)
        node_cards = _load_node_cards(input_store, tree_manifest)
        node_summaries = _load_node_summaries(input_store, tree_manifest)
        if not nodes:
            msg = "tree compaction requires committed hierarchy nodes"
            raise ValueError(msg)
        if not node_cards:
            msg = "tree compaction requires node cards"
            raise ValueError(msg)

        compaction_root = (
            request.artifact_root
            if request.artifact_root is not None
            else _default_compaction_root(request=request, tree_manifest_ref=tree_manifest_ref)
        )
        configured_compaction_root = str(compaction_root)
        output_store = build_document_store(
            self._storage,
            default_filesystem_root=configured_compaction_root,
        )
        resolved_artifact_root = output_store.resolve_artifact_root(
            run_type="tree_compaction",
            run_id=request.compaction_run_id,
            document_id=tree_manifest.document_id,
            configured_root=configured_compaction_root,
        )
        run_marker_root = reservation_artifact_root(
            resolved_artifact_root,
            marker_name=tree_manifest.document_id,
        )
        run_store = output_store.for_run(
            run_type="tree_compaction",
            run_id=request.compaction_run_id,
            document_id=tree_manifest.document_id,
        )
        expected_identity = {
            "document_id": tree_manifest.document_id,
            "tree_manifest_path": tree_manifest_ref,
            "settings_digest": settings_digest(request.settings),
        }
        created, run_record = output_store.reserve_run(
            run_type="tree_compaction",
            run_id=request.compaction_run_id,
            document_id=tree_manifest.document_id,
            artifact_root=run_marker_root,
            identity=expected_identity,
        )
        if not created:
            if run_identity_matches(run_record, expected_identity):
                manifest_ref = cast(
                    str | None,
                    run_record.get("manifest_ref") or run_record.get("manifest_path"),
                )
                if manifest_ref is None:
                    msg = "tree compaction run index points to a missing manifest"
                    raise RuntimeError(msg)
                return CompactedTreeManifest.model_validate_json(
                    canonical_json_text(output_store.read_json_artifact(manifest_ref))
                )
            msg = "tree compaction run already exists with a different source tree or settings"
            raise RuntimeError(msg)

        compacted_tree = _build_compacted_tree(
            nodes=nodes,
            node_cards=node_cards,
            node_summaries=node_summaries,
            request=request,
        )
        node_mappings = _build_node_mappings(compacted_tree)

        compacted_tree_path = run_store.put_json(
            artifact_kind="compaction",
            artifact_path="compaction/compacted-tree.json",
            payload=compacted_tree,
        )
        node_mapping_path = run_store.put_json(
            artifact_kind="compaction",
            artifact_path="compaction/node-mapping.json",
            payload=node_mappings,
        )
        manifest = CompactedTreeManifest(
            document_id=tree_manifest.document_id,
            tree_run_id=tree_manifest.tree_run_id,
            compaction_run_id=request.compaction_run_id,
            artifact_root=resolved_artifact_root,
            compacted_tree_path=compacted_tree_path,
            node_mapping_path=node_mapping_path,
            source_tree_manifest_path=tree_manifest_ref,
        )
        manifest_ref = run_store.put_json(
            artifact_kind="manifest",
            artifact_path="manifest.json",
            payload=manifest,
        )
        run_store.complete(manifest_ref=manifest_ref, manifest=manifest)
        return manifest


def load_compacted_tree_manifest(
    path: str | Path,
    *,
    storage: StorageConfig | None = None,
) -> CompactedTreeManifest:
    """Load a persisted tree-compaction manifest from JSON."""

    ref = str(path)
    if not is_postgres_ref(ref):
        return CompactedTreeManifest.model_validate_json(Path(ref).read_text(encoding="utf-8"))
    if storage is None:
        msg = (
            f"load_compacted_tree_manifest: ref {ref!r} is a PostgreSQL artifact ref "
            "but no storage config was provided; pass storage=<PostgresStorageConfig>"
        )
        raise ValueError(msg)
    store = build_document_store(storage)
    return CompactedTreeManifest.model_validate_json(
        canonical_json_text(store.read_json_artifact(ref))
    )


def load_compacted_tree(
    path: str | Path,
    *,
    storage: StorageConfig | None = None,
) -> tuple[CompactedTreeNode, ...]:
    """Load persisted compacted tree nodes from JSON."""

    ref = str(path)
    if not is_postgres_ref(ref):
        payload = cast(list[dict[str, Any]], json.loads(Path(ref).read_text(encoding="utf-8")))
    else:
        if storage is None:
            msg = (
                f"load_compacted_tree: ref {ref!r} is a PostgreSQL artifact ref "
                "but no storage config was provided; pass storage=<PostgresStorageConfig>"
            )
            raise ValueError(msg)
        store = build_document_store(storage)
        payload = cast(list[dict[str, Any]], store.read_json_artifact(ref))
    return tuple(CompactedTreeNode.model_validate_json(json.dumps(item)) for item in payload)


def load_compacted_node_mappings(
    path: str | Path,
    *,
    storage: StorageConfig | None = None,
) -> tuple[CompactedNodeMapping, ...]:
    """Load persisted serving-node mappings from JSON."""

    ref = str(path)
    if not is_postgres_ref(ref):
        payload = cast(list[dict[str, Any]], json.loads(Path(ref).read_text(encoding="utf-8")))
    else:
        if storage is None:
            msg = (
                f"load_compacted_node_mappings: ref {ref!r} is a PostgreSQL artifact ref "
                "but no storage config was provided; pass storage=<PostgresStorageConfig>"
            )
            raise ValueError(msg)
        store = build_document_store(storage)
        payload = cast(list[dict[str, Any]], store.read_json_artifact(ref))
    return tuple(CompactedNodeMapping.model_validate_json(json.dumps(item)) for item in payload)


def expand_serving_node_ids_to_canonical_node_ids(
    serving_node_ids: tuple[str, ...],
    mappings: tuple[CompactedNodeMapping, ...],
) -> tuple[str, ...]:
    """Expand serving-node ids into an ordered deduplicated canonical-node set."""

    mappings_by_id = {mapping.serving_node_id: mapping for mapping in mappings}
    expanded: list[str] = []
    seen: set[str] = set()
    for serving_node_id in serving_node_ids:
        mapping = mappings_by_id.get(serving_node_id)
        if mapping is None:
            msg = f"unknown serving_node_id {serving_node_id!r}"
            raise ValueError(msg)
        for canonical_node_id in mapping.canonical_node_ids:
            if canonical_node_id in seen:
                continue
            seen.add(canonical_node_id)
            expanded.append(canonical_node_id)
    return tuple(expanded)


def compact_tree(
    request: TreeCompactionRequest,
    *,
    storage: StorageConfig | None = None,
) -> CompactedTreeManifest:
    """Convenience wrapper for one tree-compaction run."""

    return TreeCompactionService(storage=storage).compact(request)


__all__ = [
    "TreeCompactionService",
    "compact_tree",
    "expand_serving_node_ids_to_canonical_node_ids",
    "load_compacted_node_mappings",
    "load_compacted_tree",
    "load_compacted_tree_manifest",
]
