"""Deterministic-first large-node decomposition over normalized synthesis text."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from strataforge.domain.models import (
    ContentSpan,
    DecompositionBoundary,
    DecompositionMethod,
    DecompositionPromptResponse,
    DecompositionReport,
    HierarchyNode,
    HierarchyOrigin,
    NodeAnchor,
    NodeOwnedSpan,
    OutlineEntry,
    PageSpan,
    SemanticUsage,
    TreeSettings,
)
from strataforge.llm.prompts import build_decomposition_messages
from strataforge.llm.protocols import StructuredLLMGateway
from strataforge.llm.types import GatewayRequest, GatewayUsage
from strataforge.semantic.tokens import Tokenizer, resolve_tokenizer
from strataforge.tree.anchors import node_anchor_to_source_anchor
from strataforge.tree.headings import (
    PageArtifacts,
    anchor_title_on_page,
    extract_inferred_candidates,
    normalized_title_key,
)
from strataforge.tree.hierarchy import generate_node_id

_DECOMPOSITION_KEEP_THRESHOLD = 20
_DECOMPOSITION_HIGH_CONFIDENCE_THRESHOLD = 40
_MAX_LLM_PAGE_TEXT_CHARS = 12000


@dataclass(frozen=True)
class _DecompositionMetadata:
    provider_name: str
    assurance_mode: str
    usage: SemanticUsage | None
    audit_path: str | None


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    return str(path)


def _stable_node_order(node: HierarchyNode) -> tuple[int, int, int, str]:
    return (
        node.page_span.start_page,
        node.heading_anchor.start_offset,
        node.level,
        node.node_id,
    )


def _usage_snapshot(usage: GatewayUsage | None) -> SemanticUsage | None:
    if usage is None:
        return None
    return SemanticUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def _combine_usage(left: SemanticUsage | None, right: SemanticUsage | None) -> SemanticUsage | None:
    if left is None:
        return right
    if right is None:
        return left
    return SemanticUsage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
    )


def _node_pages(
    node: HierarchyNode,
    pages_by_index: dict[int, PageArtifacts],
) -> tuple[PageArtifacts, ...]:
    return tuple(
        pages_by_index[page_index]
        for page_index in range(node.page_span.start_page, node.page_span.end_page + 1)
        if page_index in pages_by_index
    )


def _is_leaf(node: HierarchyNode, parent_ids: set[str]) -> bool:
    return node.node_id not in parent_ids


def _candidate_level(parent: HierarchyNode, level_hint: int | None) -> int:
    if level_hint is not None and level_hint > parent.level:
        return level_hint
    return parent.level + 1


def _is_credible_subheading(candidate: Any) -> bool:
    breakdown = candidate.score_breakdown
    return candidate.keep and (
        candidate.anchor.start_offset == 0
        or candidate.level_hint is not None
        or breakdown.uppercase_signal > 0
        or breakdown.title_case_signal > 0
        or breakdown.toc_overlap_signal > 0
    )


def _bounded_llm_page_text(pages: tuple[PageArtifacts, ...]) -> str:
    parts: list[str] = []
    remaining = _MAX_LLM_PAGE_TEXT_CHARS
    for page in pages:
        if remaining <= 0:
            break
        body = page.text[:remaining].strip()
        marker = f"<page_{page.page_index}>"
        parts.append(f"{marker}\n{body}")
        remaining -= len(marker) + len(body) + 2
    return "\n\n".join(parts).strip()


def _owned_spans_are_empty(node: HierarchyNode) -> bool:
    if not node.owned_spans:
        return True
    return all(
        span.span.start_page == span.span.end_page
        and span.span.start_offset == span.span.end_offset
        for span in node.owned_spans
    )


def _parent_owned_end(
    node: HierarchyNode,
    pages_by_index: dict[int, PageArtifacts],
) -> tuple[int, int]:
    if node.owned_spans:
        last = node.owned_spans[-1].span
        return last.end_page, last.end_offset
    last_page = node.page_span.end_page
    last_offset = len(pages_by_index[last_page].text) if last_page in pages_by_index else 0
    return last_page, last_offset


class NodeDecomposer:
    """Deterministic-first decomposition over normalized synthesis text."""

    def __init__(
        self,
        settings: TreeSettings,
        gateway: StructuredLLMGateway | None = None,
        tokenizer: Tokenizer | None = None,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._tokenizer = resolve_tokenizer(tokenizer)
        self._artifact_path: str | None = None

    @property
    def artifact_path(self) -> str | None:
        return self._artifact_path

    def decompose(
        self,
        *,
        nodes: tuple[HierarchyNode, ...],
        pages: tuple[PageArtifacts, ...],
        tree_run_id: str,
        artifact_root: str | None = None,
    ) -> tuple[tuple[HierarchyNode, ...], DecompositionReport]:
        del tree_run_id
        pages_by_index = {page.page_index: page for page in pages}
        current_nodes = tuple(sorted(nodes, key=_stable_node_order))
        decomposed_node_ids: list[str] = []
        new_child_count = 0
        empty_parent_count = 0
        used_llm = False
        max_depth_used = 0
        provider_name: str | None = None
        assurance_mode: str | None = None
        gateway_usage: SemanticUsage | None = None
        gateway_audit_paths: list[str] = []

        for depth in range(1, self._settings.max_decomposition_depth + 1):
            parent_ids = {node.parent_id for node in current_nodes if node.parent_id is not None}
            depth_changed = False
            next_nodes = list(current_nodes)

            for node in list(current_nodes):
                if not _is_leaf(node, parent_ids):
                    continue
                if not self._needs_decomposition(node, pages_by_index):
                    continue

                result = self._decompose_node(node=node, pages_by_index=pages_by_index)
                if result is None:
                    continue

                truncated_parent, children, method, metadata = result
                next_nodes = [
                    existing for existing in next_nodes if existing.node_id != node.node_id
                ]
                next_nodes.append(truncated_parent)
                next_nodes.extend(children)
                decomposed_node_ids.append(node.node_id)
                new_child_count += len(children)
                if _owned_spans_are_empty(truncated_parent):
                    empty_parent_count += 1
                if metadata is not None:
                    provider_name = metadata.provider_name
                    assurance_mode = metadata.assurance_mode
                    gateway_usage = _combine_usage(gateway_usage, metadata.usage)
                    if metadata.audit_path is not None:
                        gateway_audit_paths.append(metadata.audit_path)
                used_llm = used_llm or method is DecompositionMethod.LLM_ASSISTED
                depth_changed = True

            current_nodes = tuple(sorted(next_nodes, key=_stable_node_order))
            if depth_changed:
                max_depth_used = depth
                continue
            break

        if new_child_count == 0:
            method = DecompositionMethod.NONE
        elif used_llm:
            method = DecompositionMethod.LLM_ASSISTED
        else:
            method = DecompositionMethod.DETERMINISTIC

        report = DecompositionReport(
            decomposed_node_ids=tuple(decomposed_node_ids),
            new_child_count=new_child_count,
            empty_parent_count=empty_parent_count,
            decomposition_method=method,
            depth=max_depth_used,
            tokenizer_identity=self._tokenizer.identity,
            gateway_provider_name=provider_name,
            gateway_assurance_mode=assurance_mode,
            gateway_usage=gateway_usage,
            gateway_audit_paths=tuple(gateway_audit_paths),
        )
        if artifact_root is not None:
            self._artifact_path = _write_json(
                Path(artifact_root) / "decomposition" / "report.json", report
            )
        return current_nodes, report

    def _needs_decomposition(
        self,
        node: HierarchyNode,
        pages_by_index: dict[int, PageArtifacts],
    ) -> bool:
        page_length = node.page_span.end_page - node.page_span.start_page + 1
        if page_length > self._settings.max_pages_per_leaf_node:
            return True
        return _token_count_for_node(node, pages_by_index, self._tokenizer) > (
            self._settings.max_tokens_per_leaf_node
        )

    def _decompose_node(
        self,
        *,
        node: HierarchyNode,
        pages_by_index: dict[int, PageArtifacts],
    ) -> (
        tuple[
            HierarchyNode,
            tuple[HierarchyNode, ...],
            DecompositionMethod,
            _DecompositionMetadata | None,
        ]
        | None
    ):
        pages = _node_pages(node, pages_by_index)
        deterministic_children = self._deterministic_children(node=node, pages=pages)
        if len(deterministic_children) >= 2:
            truncated_parent = self._refine_parent_owned_spans(node, deterministic_children)
            return (
                truncated_parent,
                deterministic_children,
                DecompositionMethod.DETERMINISTIC,
                None,
            )

        if self._gateway is None:
            return None

        llm_children, metadata = self._llm_children(node=node, pages=pages)
        if len(llm_children) < 2:
            return None
        truncated_parent = self._refine_parent_owned_spans(node, llm_children)
        return (
            truncated_parent,
            llm_children,
            DecompositionMethod.LLM_ASSISTED,
            metadata,
        )

    def _deterministic_children(
        self,
        *,
        node: HierarchyNode,
        pages: tuple[PageArtifacts, ...],
    ) -> tuple[HierarchyNode, ...]:
        local_settings = self._settings.model_copy(
            update={
                "heading_score_keep_threshold": _DECOMPOSITION_KEEP_THRESHOLD,
                "heading_score_high_confidence_threshold": _DECOMPOSITION_HIGH_CONFIDENCE_THRESHOLD,
            }
        )
        candidates = extract_inferred_candidates(
            document_id=node.document_id,
            pages=pages,
            outline_entries=cast(tuple[OutlineEntry, ...], ()),
            settings=local_settings,
        )
        credible_candidates = tuple(
            candidate
            for candidate in candidates
            if _is_credible_subheading(candidate)
            and self._candidate_belongs_to_child(candidate.anchor, node)
        )
        return self._children_from_anchors(
            node=node,
            boundaries=tuple(
                DecompositionBoundary(
                    title=candidate.title,
                    page_index=candidate.page_index,
                    level_hint=candidate.level_hint,
                )
                for candidate in credible_candidates
            ),
            pages=pages,
            method=DecompositionMethod.DETERMINISTIC,
        )

    def _llm_children(
        self,
        *,
        node: HierarchyNode,
        pages: tuple[PageArtifacts, ...],
    ) -> tuple[tuple[HierarchyNode, ...], _DecompositionMetadata]:
        assert self._gateway is not None
        response = self._gateway.invoke(
            GatewayRequest[DecompositionPromptResponse](
                operation_name="decompose_large_node",
                messages=build_decomposition_messages(
                    node_title=node.title,
                    page_text=_bounded_llm_page_text(pages),
                ),
                response_model=DecompositionPromptResponse,
            )
        )
        return (
            self._children_from_anchors(
                node=node,
                boundaries=response.output.entries,
                pages=pages,
                method=DecompositionMethod.LLM_ASSISTED,
            ),
            _DecompositionMetadata(
                provider_name=response.provider_name,
                assurance_mode=response.assurance_mode.value,
                usage=_usage_snapshot(response.usage),
                audit_path=response.audit_path,
            ),
        )

    def _children_from_anchors(
        self,
        *,
        node: HierarchyNode,
        boundaries: tuple[DecompositionBoundary, ...],
        pages: tuple[PageArtifacts, ...],
        method: DecompositionMethod,
    ) -> tuple[HierarchyNode, ...]:
        pages_by_index = {page.page_index: page for page in pages}
        anchored: list[tuple[DecompositionBoundary, NodeAnchor]] = []
        seen_positions: set[tuple[int, int, int]] = set()

        for boundary in boundaries:
            page = pages_by_index.get(boundary.page_index)
            if page is None:
                continue
            anchor = anchor_title_on_page(boundary.title, page)
            if anchor is None or not self._candidate_belongs_to_child(anchor, node):
                continue
            position = (anchor.page, anchor.start_offset, anchor.end_offset)
            if position in seen_positions:
                continue
            seen_positions.add(position)
            anchored.append((boundary, anchor))

        anchored.sort(key=lambda item: (item[1].page, item[1].start_offset, item[0].title))
        if len(anchored) < 2:
            return ()

        children: list[HierarchyNode] = []
        parent_end_page, parent_end_offset = _parent_owned_end(node, pages_by_index)
        for index, (boundary, anchor) in enumerate(anchored):
            next_anchor = anchored[index + 1][1] if index + 1 < len(anchored) else None
            if next_anchor is not None:
                child_end_page = next_anchor.page
                child_end_offset = next_anchor.start_offset
            else:
                child_end_page = parent_end_page
                child_end_offset = parent_end_offset

            level = _candidate_level(node, boundary.level_hint)
            title = boundary.title.strip()
            path = (*node.path, title)
            child = HierarchyNode(
                node_id=generate_node_id(
                    document_id=node.document_id,
                    path=path,
                    level=level,
                    page=anchor.page,
                    start_offset=anchor.start_offset,
                    end_offset=anchor.end_offset,
                    span_start_page=anchor.page,
                ),
                document_id=node.document_id,
                parent_id=node.node_id,
                path=path,
                level=level,
                title=title,
                normalized_title=normalized_title_key(title),
                page_span=PageSpan(
                    start_page=anchor.page,
                    end_page=max(anchor.page, child_end_page),
                ),
                heading_anchor=anchor,
                owned_spans=(
                    NodeOwnedSpan(
                        kind="body",
                        span=ContentSpan(
                            start_page=anchor.page,
                            start_offset=anchor.start_offset,
                            end_page=child_end_page,
                            end_offset=child_end_offset,
                        ),
                    ),
                ),
                source_anchors=(node_anchor_to_source_anchor(anchor),),
                origin=(
                    HierarchyOrigin.INFERRED
                    if method is DecompositionMethod.DETERMINISTIC
                    else HierarchyOrigin.HYBRID
                ),
                confidence=0.72 if method is DecompositionMethod.DETERMINISTIC else 0.6,
            )
            children.append(child)
        return tuple(children)

    def _refine_parent_owned_spans(
        self,
        node: HierarchyNode,
        children: tuple[HierarchyNode, ...],
    ) -> HierarchyNode:
        first_child = min(children, key=_stable_node_order)
        if node.owned_spans:
            parent_start_page = node.owned_spans[0].span.start_page
            parent_start_offset = node.owned_spans[0].span.start_offset
        else:
            parent_start_page = node.heading_anchor.page
            parent_start_offset = node.heading_anchor.start_offset
        prefix_end_page = first_child.heading_anchor.page
        prefix_end_offset = first_child.heading_anchor.start_offset

        if prefix_end_page < parent_start_page or (
            prefix_end_page == parent_start_page and prefix_end_offset < parent_start_offset
        ):
            return node.model_copy(update={"owned_spans": ()})

        return node.model_copy(
            update={
                "owned_spans": (
                    NodeOwnedSpan(
                        kind="body",
                        span=ContentSpan(
                            start_page=parent_start_page,
                            start_offset=parent_start_offset,
                            end_page=prefix_end_page,
                            end_offset=prefix_end_offset,
                        ),
                    ),
                )
            }
        )

    def _candidate_belongs_to_child(self, anchor: NodeAnchor, node: HierarchyNode) -> bool:
        if anchor.page < node.page_span.start_page or anchor.page > node.page_span.end_page:
            return False
        if anchor.page == node.heading_anchor.page:
            return anchor.start_offset > node.heading_anchor.start_offset
        return True


def _token_count_for_node(
    node: HierarchyNode,
    pages_by_index: dict[int, PageArtifacts],
    tokenizer: Tokenizer,
) -> int:
    return tokenizer.count_tokens(
        "\n".join(page.text for page in _node_pages(node, pages_by_index)).strip()
    )


__all__ = [
    "NodeDecomposer",
]
