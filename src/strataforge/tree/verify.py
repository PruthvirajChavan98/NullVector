"""Deterministic hierarchy verification for Phase 02."""

from __future__ import annotations

from strataforge.domain.models import (
    HierarchyNode,
    PageSpan,
    TitleMatchTier,
    TreeNodeVerificationResult,
    TreeSettings,
    UnassignedPageSpan,
    VerificationIssue,
    VerificationReport,
    VerificationSeverity,
    VerificationStatus,
)
from strataforge.tree.headings import (
    PageArtifacts,
    casefold_punct_key,
    normalized_title_key,
    split_text_lines_with_offsets,
    tokenize_title,
)


def determine_title_match_tier(
    title: str,
    page: PageArtifacts,
    settings: TreeSettings,
) -> TitleMatchTier:
    lines = split_text_lines_with_offsets(page.text, page.page_index)
    candidates = list(lines[: settings.top_of_page_line_limit])
    normalized_title = normalized_title_key(title)
    punct_title = casefold_punct_key(title)

    for line in candidates:
        if line.normalized_text == normalized_title:
            return TitleMatchTier.EXACT_NORMALIZED
    for line in candidates:
        if line.casefold_punct_text == punct_title:
            return TitleMatchTier.CASEFOLD_PUNCT

    title_tokens = set(tokenize_title(title))
    if title_tokens:
        for line in candidates:
            line_tokens = set(tokenize_title(line.text))
            if not line_tokens:
                continue
            containment = len(title_tokens & line_tokens) / len(title_tokens)
            if containment >= settings.title_token_containment_threshold:
                return TitleMatchTier.TOKEN_CONTAINMENT

    if len(normalized_title) <= settings.short_title_max_length_for_edit_distance:
        for line in candidates:
            distance = _levenshtein_distance(normalized_title, line.normalized_text)
            if distance <= settings.short_title_edit_distance_threshold:
                return TitleMatchTier.EDIT_DISTANCE

    return TitleMatchTier.NONE


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + cost,
                ),
            )
        previous = current
    return previous[-1]


def verify_hierarchy(
    *,
    document_id: str,
    tree_run_id: str,
    page_count: int,
    nodes: tuple[HierarchyNode, ...],
    pages: tuple[PageArtifacts, ...],
    unassigned_spans: tuple[UnassignedPageSpan, ...],
    settings: TreeSettings,
) -> tuple[tuple[HierarchyNode, ...], VerificationReport]:
    """Verify title grounding, level/span consistency, and page coverage."""

    pages_by_index = {page.page_index: page for page in pages}
    nodes_by_id = {node.node_id: node for node in nodes}
    node_results: list[TreeNodeVerificationResult] = []
    verified_nodes: list[HierarchyNode] = []

    for node in nodes:
        issues: list[VerificationIssue] = []
        page = pages_by_index.get(node.heading_anchor.page)
        match_tier = TitleMatchTier.NONE
        if page is None:
            issues.append(
                VerificationIssue(
                    code="missing-heading-page",
                    message="heading page artifact could not be loaded",
                    severity=VerificationSeverity.ERROR,
                    page_span=node.page_span,
                ),
            )
        else:
            match_tier = determine_title_match_tier(node.title, page, settings)
            if match_tier == TitleMatchTier.NONE:
                issues.append(
                    VerificationIssue(
                        code="heading-title-mismatch",
                        message="node title could not be matched against bounded page-local lines",
                        severity=VerificationSeverity.ERROR,
                        page_span=node.page_span,
                    ),
                )

        parent = nodes_by_id.get(node.parent_id) if node.parent_id is not None else None
        if parent is not None and not (
            parent.page_span.start_page
            <= node.page_span.start_page
            <= node.page_span.end_page
            <= parent.page_span.end_page
        ):
            issues.append(
                VerificationIssue(
                    code="child-outside-parent-span",
                    message="child node span must remain inside its parent span",
                    severity=VerificationSeverity.ERROR,
                    page_span=node.page_span,
                ),
            )
        if parent is not None and node.level > parent.level + 1:
            issues.append(
                VerificationIssue(
                    code="impossible-level-jump",
                    message="node levels may not jump by more than one relative to the parent",
                    severity=VerificationSeverity.ERROR,
                    page_span=node.page_span,
                ),
            )

        verified_node = node.model_copy(update={"verification_match_tier": match_tier})
        verified_nodes.append(verified_node)
        if issues:
            node_results.append(
                TreeNodeVerificationResult(
                    document_id=document_id,
                    tree_run_id=tree_run_id,
                    subject_id=node.node_id,
                    status=VerificationStatus.FAILED,
                    issues=tuple(issues),
                    covered_page_span=node.page_span,
                    notes=(f"match_tier:{match_tier.value}",),
                ),
            )
            continue
        node_results.append(
            TreeNodeVerificationResult(
                document_id=document_id,
                tree_run_id=tree_run_id,
                subject_id=node.node_id,
                status=VerificationStatus.PASSED,
                covered_page_span=node.page_span,
                notes=(f"match_tier:{match_tier.value}",),
            ),
        )

    coverage = [False] * page_count
    for node in nodes:
        for page_index in range(node.page_span.start_page, node.page_span.end_page + 1):
            coverage[page_index] = True
    for gap in unassigned_spans:
        for page_index in range(gap.page_span.start_page, gap.page_span.end_page + 1):
            coverage[page_index] = True

    document_issues: list[VerificationIssue] = []
    for page_index, is_covered in enumerate(coverage):
        if not is_covered:
            document_issues.append(
                VerificationIssue(
                    code="unreported-coverage-gap",
                    message=(
                        f"page {page_index} is neither covered by a node nor by an unassigned span"
                    ),
                    severity=VerificationSeverity.ERROR,
                    page_span=PageSpan(start_page=page_index, end_page=page_index),
                ),
            )

    has_node_failure = any(result.status != VerificationStatus.PASSED for result in node_results)
    report_status = (
        VerificationStatus.FAILED
        if has_node_failure or document_issues
        else VerificationStatus.PASSED
    )
    report = VerificationReport(
        document_id=document_id,
        tree_run_id=tree_run_id,
        status=report_status,
        node_results=tuple(node_results),
        document_issues=tuple(document_issues),
        unassigned_spans=unassigned_spans,
        notes=(
            f"verified_nodes:{len(nodes)}",
            f"explicit_unassigned_spans:{len(unassigned_spans)}",
        ),
    )
    return tuple(verified_nodes), report
