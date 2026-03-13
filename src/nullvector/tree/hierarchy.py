"""Hierarchy assembly, trust evaluation, and span consolidation for Phase 02."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from nullvector.domain.models import (
    ContentSpan,
    HeadingCandidate,
    HeadingSourceKind,
    HierarchyNode,
    HierarchyOrigin,
    NodeCard,
    NodeOwnedSpan,
    OutlineQualityReport,
    OutlineSource,
    OutlineTrustMode,
    PageSpan,
    RepairKind,
    RepairRequest,
    TreeSettings,
    UnassignedPageSpan,
)
from nullvector.tree.anchors import node_anchor_to_source_anchor
from nullvector.tree.headings import PageArtifacts, numbering_depth


@dataclass(frozen=True)
class _ResolvedHeading:
    candidate: HeadingCandidate
    level: int
    origin: HierarchyOrigin
    ambiguous: bool


def normalize_path_segment(value: str) -> str:
    """Normalize a path segment for stable hashing and rerun diffs."""

    return " ".join(value.split()).casefold()


def generate_node_id(
    document_id: str,
    path: tuple[str, ...],
    level: int,
    page: int,
    start_offset: int,
    end_offset: int,
    span_start_page: int,
) -> str:
    """Create a stable node id from document/path/anchor/span-start inputs."""

    normalized_path = "|".join(normalize_path_segment(segment) for segment in path)
    payload = (
        f"{document_id}|{normalized_path}|{level}|"
        f"{page}|{start_offset}|{end_offset}|{span_start_page}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _selected_outline_report(
    selected_source: OutlineSource,
    outline_reports: Sequence[OutlineQualityReport],
) -> OutlineQualityReport | None:
    for report in outline_reports:
        if report.source == selected_source:
            return report
    return None


def _candidates_match(
    left: HeadingCandidate,
    right: HeadingCandidate,
    settings: TreeSettings,
) -> bool:
    return (
        left.normalized_title == right.normalized_title
        and abs(left.page_index - right.page_index) <= settings.maximum_allowed_page_adjacency
    )


def determine_outline_trust_mode(
    *,
    selected_source: OutlineSource,
    outline_reports: Sequence[OutlineQualityReport],
    outline_candidates: Sequence[HeadingCandidate],
    inferred_candidates: Sequence[HeadingCandidate],
    toc_candidates: Sequence[HeadingCandidate] = (),
    settings: TreeSettings,
) -> OutlineTrustMode:
    """Choose outline-primary, hybrid, or inferred-primary deterministically."""

    if selected_source == OutlineSource.NONE or not outline_candidates:
        if toc_candidates:
            return OutlineTrustMode.TOC_RECONCILED
        return OutlineTrustMode.INFERRED_PRIMARY

    selected_report = _selected_outline_report(selected_source, outline_reports)
    if selected_report is None:
        if toc_candidates:
            return OutlineTrustMode.TOC_RECONCILED
        return OutlineTrustMode.INFERRED_PRIMARY

    if selected_report.entry_count == 0:
        null_destination_rate = 0.0
    else:
        null_destination_rate = selected_report.null_destination_count / selected_report.entry_count

    high_confidence = [candidate for candidate in inferred_candidates if candidate.high_confidence]
    if high_confidence:
        matched = sum(
            1
            for inferred in high_confidence
            if any(_candidates_match(inferred, outline, settings) for outline in outline_candidates)
        )
        agreement_ratio = matched / len(high_confidence)
    else:
        agreement_ratio = 1.0

    if toc_candidates and (
        selected_report.invalid_level_count > 0
        or null_destination_rate > settings.outline_null_destination_rate_threshold
        or agreement_ratio < settings.outline_high_agreement_threshold
    ):
        return OutlineTrustMode.TOC_RECONCILED

    if (
        selected_report.invalid_level_count == 0
        and null_destination_rate <= settings.outline_null_destination_rate_threshold
        and agreement_ratio >= settings.outline_high_agreement_threshold
    ):
        return OutlineTrustMode.OUTLINE_PRIMARY
    if agreement_ratio < settings.outline_low_agreement_threshold:
        return OutlineTrustMode.INFERRED_PRIMARY
    return OutlineTrustMode.HYBRID


def _deduplicate_candidates(
    candidates: Sequence[HeadingCandidate],
    settings: TreeSettings,
) -> tuple[HeadingCandidate, ...]:
    deduplicated: list[HeadingCandidate] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            item.page_index,
            item.anchor.start_offset,
            -item.score_breakdown.final_score,
            item.title,
        ),
    ):
        if any(_candidates_match(candidate, existing, settings) for existing in deduplicated):
            continue
        deduplicated.append(candidate)
    return tuple(deduplicated)


def reconcile_heading_candidates(
    *,
    outline_candidates: Sequence[HeadingCandidate],
    inferred_candidates: Sequence[HeadingCandidate],
    trust_mode: OutlineTrustMode,
    toc_candidates: Sequence[HeadingCandidate] = (),
    settings: TreeSettings,
) -> tuple[HeadingCandidate, ...]:
    """Select and reconcile the heading sequence used for hierarchy assembly."""

    kept_inferred = [candidate for candidate in inferred_candidates if candidate.keep]
    if trust_mode == OutlineTrustMode.OUTLINE_PRIMARY:
        return _deduplicate_candidates(outline_candidates, settings)
    if trust_mode == OutlineTrustMode.INFERRED_PRIMARY:
        return _deduplicate_candidates(kept_inferred, settings)
    if trust_mode == OutlineTrustMode.TOC_RECONCILED:
        merged = list(outline_candidates)
        merged.extend(toc_candidates)
        for candidate in kept_inferred:
            if any(_candidates_match(candidate, existing, settings) for existing in merged):
                continue
            merged.append(candidate)
        return _deduplicate_candidates(merged, settings)

    merged = list(outline_candidates)
    for candidate in kept_inferred:
        if any(_candidates_match(candidate, outline, settings) for outline in outline_candidates):
            continue
        merged.append(candidate)
    return _deduplicate_candidates(merged, settings)


def _origin_for_candidate(
    candidate: HeadingCandidate,
    trust_mode: OutlineTrustMode,
) -> HierarchyOrigin:
    if trust_mode == OutlineTrustMode.HYBRID:
        return HierarchyOrigin.HYBRID
    if candidate.source_kind == HeadingSourceKind.OUTLINE:
        return HierarchyOrigin.OUTLINE
    return HierarchyOrigin.INFERRED


def _hinted_level(candidate: HeadingCandidate) -> int | None:
    numbered_level = numbering_depth(candidate.title)
    if numbered_level is not None:
        return numbered_level
    if candidate.outline_level_hint is not None:
        return candidate.outline_level_hint
    if candidate.level_hint is not None:
        return candidate.level_hint
    return None


def _resolve_heading_levels(
    candidates: Sequence[HeadingCandidate],
    trust_mode: OutlineTrustMode,
) -> tuple[_ResolvedHeading, ...]:
    hinted_levels = [_hinted_level(candidate) for candidate in candidates]
    resolved: list[_ResolvedHeading] = []
    previous_level: int | None = None
    for index, candidate in enumerate(candidates):
        hinted = hinted_levels[index]
        ambiguous = False
        if hinted is not None:
            level = hinted
        else:
            ambiguous = True
            next_hinted = next(
                (level for level in hinted_levels[index + 1 :] if level is not None), None
            )
            if (
                previous_level is not None
                and next_hinted is not None
                and previous_level == next_hinted
            ):
                level = previous_level + 1
            elif previous_level is not None:
                level = previous_level
            else:
                level = 1
        if previous_level is not None and level > previous_level + 1:
            level = previous_level + 1
            ambiguous = True
        previous_level = level
        resolved.append(
            _ResolvedHeading(
                candidate=candidate,
                level=level,
                origin=_origin_for_candidate(candidate, trust_mode),
                ambiguous=ambiguous,
            ),
        )
    return tuple(resolved)


def build_hierarchy(
    *,
    document_id: str,
    candidates: Sequence[HeadingCandidate],
    page_count: int,
    trust_mode: OutlineTrustMode,
    gap_pages: set[int] | None = None,
) -> tuple[tuple[HierarchyNode, ...], tuple[RepairRequest, ...], int]:
    """Build a preorder hierarchy and emit bounded repair requests for ambiguities."""

    resolved_headings = _resolve_heading_levels(candidates, trust_mode)
    if not resolved_headings:
        return (), (), 0

    repair_requests: list[RepairRequest] = []
    temporary_nodes: list[HierarchyNode] = []
    stack: list[HierarchyNode] = []
    ambiguity_count = 0

    for resolved in resolved_headings:
        candidate = resolved.candidate
        while stack and stack[-1].level >= resolved.level:
            stack.pop()

        parent = stack[-1] if stack else None
        path = (candidate.title,) if parent is None else (*parent.path, candidate.title)
        node_id = generate_node_id(
            document_id=document_id,
            path=path,
            level=resolved.level,
            page=candidate.anchor.page,
            start_offset=candidate.anchor.start_offset,
            end_offset=candidate.anchor.end_offset,
            span_start_page=candidate.page_index,
        )
        if resolved.ambiguous:
            ambiguity_count += 1
            repair_requests.append(
                RepairRequest(
                    request_id=f"{candidate.page_index}-{candidate.anchor.start_offset}-{node_id[:12]}",
                    subject_id=node_id,
                    repair_kind=RepairKind.ADJACENT_LEVEL_AMBIGUITY,
                    rationale="deterministic level inference required a fallback heuristic",
                    details={
                        "candidate_title": candidate.title,
                        "page_index": str(candidate.page_index),
                    },
                ),
            )

        temporary_node = HierarchyNode(
            node_id=node_id,
            document_id=document_id,
            parent_id=parent.node_id if parent is not None else None,
            path=path,
            level=resolved.level,
            title=candidate.title,
            normalized_title=candidate.normalized_title,
            page_span=PageSpan(start_page=candidate.page_index, end_page=candidate.page_index),
            heading_anchor=candidate.anchor,
            owned_spans=(
                NodeOwnedSpan(
                    kind="body",
                    span=ContentSpan(
                        start_page=candidate.page_index,
                        start_offset=candidate.anchor.start_offset,
                        end_page=candidate.page_index,
                        end_offset=candidate.anchor.end_offset,
                    ),
                ),
            ),
            source_anchors=(node_anchor_to_source_anchor(candidate.anchor),),
            origin=resolved.origin,
            confidence=max(0.0, min(candidate.score_breakdown.final_score / 100.0, 1.0)),
        )
        temporary_nodes.append(temporary_node)
        stack.append(temporary_node)

    finalized_nodes: list[HierarchyNode] = []
    gap_pages = gap_pages or set()
    for index, node in enumerate(temporary_nodes):
        end_page = node.page_span.start_page
        for later in temporary_nodes[index + 1 :]:
            if later.level <= node.level:
                end_page = (
                    later.page_span.start_page
                    if later.page_span.start_page == node.page_span.start_page
                    else later.page_span.start_page - 1
                )
                break
            end_page = max(end_page, later.page_span.start_page)
        while end_page > node.page_span.start_page and end_page in gap_pages:
            end_page -= 1
        end_page = min(end_page, page_count - 1)
        if end_page < node.page_span.start_page:
            end_page = node.page_span.start_page
        finalized_nodes.append(
            node.model_copy(
                update={
                    "page_span": PageSpan(start_page=node.page_span.start_page, end_page=end_page)
                }
            )
        )

    return tuple(finalized_nodes), tuple(repair_requests), ambiguity_count


def compute_unassigned_spans(
    *,
    document_id: str,
    page_count: int,
    nodes: Sequence[HierarchyNode],
) -> tuple[UnassignedPageSpan, ...]:
    """Emit explicit coverage gaps instead of inventing a synthetic root node."""

    covered = [False] * page_count
    for node in nodes:
        for page_index in range(node.page_span.start_page, node.page_span.end_page + 1):
            covered[page_index] = True

    first_covered = next((index for index, is_covered in enumerate(covered) if is_covered), None)
    last_covered = next(
        (index for index in range(page_count - 1, -1, -1) if covered[index]),
        None,
    )
    spans: list[UnassignedPageSpan] = []
    span_start: int | None = None
    for index, is_covered in enumerate(covered):
        if not is_covered and span_start is None:
            span_start = index
        if is_covered and span_start is not None:
            spans.append(
                UnassignedPageSpan(
                    document_id=document_id,
                    reason=_gap_reason(span_start, index - 1, first_covered, last_covered),
                    page_span=PageSpan(start_page=span_start, end_page=index - 1),
                ),
            )
            span_start = None
    if span_start is not None:
        spans.append(
            UnassignedPageSpan(
                document_id=document_id,
                reason=_gap_reason(span_start, page_count - 1, first_covered, last_covered),
                page_span=PageSpan(start_page=span_start, end_page=page_count - 1),
            ),
        )
    return tuple(spans)


def _gap_reason(
    start_page: int,
    end_page: int,
    first_covered: int | None,
    last_covered: int | None,
) -> str:
    if first_covered is None:
        return "no_verified_headings"
    if last_covered is None:
        return "no_verified_headings"
    if end_page < first_covered:
        return "before_first_heading"
    if start_page > last_covered:
        return "after_last_heading"
    return "between_verified_nodes"


def project_node_cards(nodes: Sequence[HierarchyNode]) -> tuple[NodeCard, ...]:
    """Project internal hierarchy nodes into the committed public NodeCard contract."""

    return tuple(
        NodeCard(
            node_id=node.node_id,
            document_id=node.document_id,
            path=node.path,
            level=node.level,
            title=node.title,
            page_span=node.page_span,
            owned_spans=node.owned_spans,
            source_anchors=node.source_anchors,
        )
        for node in nodes
    )


def attach_default_owned_spans(
    nodes: Sequence[HierarchyNode],
    pages: Sequence[PageArtifacts],
) -> tuple[HierarchyNode, ...]:
    """Attach coarse default ownership spans before decomposition refines them."""

    page_lengths = {page.page_index: len(page.text) for page in pages}
    updated: list[HierarchyNode] = []
    for node in nodes:
        end_offset = page_lengths.get(node.page_span.end_page, 0)
        updated.append(
            node.model_copy(
                update={
                    "owned_spans": (
                        NodeOwnedSpan(
                            kind="body",
                            span=ContentSpan(
                                start_page=node.heading_anchor.page,
                                start_offset=node.heading_anchor.start_offset,
                                end_page=node.page_span.end_page,
                                end_offset=end_offset,
                            ),
                        ),
                    )
                }
            )
        )
    return tuple(updated)
