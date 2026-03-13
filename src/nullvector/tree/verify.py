"""Deterministic hierarchy verification for Phase 02."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nullvector.domain.models import (
    ContentSpan,
    HierarchyNode,
    LLMVerificationAssistRecord,
    OutlineAnchorRecord,
    OutlineAnchorStatus,
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
from nullvector.llm.prompts import VerificationPromptResponse, build_verification_messages
from nullvector.llm.protocols import StructuredLLMGateway
from nullvector.llm.types import GatewayRequest
from nullvector.tree.headings import (
    PageArtifacts,
    PageLine,
    casefold_punct_key,
    normalized_title_key,
    split_text_lines_with_offsets,
    tokenize_title,
)


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


def _match_tier_from_lines(
    title: str,
    lines: list[PageLine],
    settings: TreeSettings,
) -> TitleMatchTier:
    normalized_title = normalized_title_key(title)
    punct_title = casefold_punct_key(title)

    for line in lines:
        if line.normalized_text == normalized_title:
            return TitleMatchTier.EXACT_NORMALIZED
    for line in lines:
        if line.casefold_punct_text == punct_title:
            return TitleMatchTier.CASEFOLD_PUNCT

    title_tokens = set(tokenize_title(title))
    if title_tokens:
        for line in lines:
            line_tokens = set(tokenize_title(line.text))
            if not line_tokens:
                continue
            containment = len(title_tokens & line_tokens) / len(title_tokens)
            if containment >= settings.title_token_containment_threshold:
                return TitleMatchTier.TOKEN_CONTAINMENT

    if len(normalized_title) <= settings.short_title_max_length_for_edit_distance:
        for line in lines:
            distance = _levenshtein_distance(normalized_title, line.normalized_text)
            if distance <= settings.short_title_edit_distance_threshold:
                return TitleMatchTier.EDIT_DISTANCE

    return TitleMatchTier.NONE


def determine_title_match_tier(
    title: str,
    page: PageArtifacts,
    settings: TreeSettings,
) -> TitleMatchTier:
    lines = split_text_lines_with_offsets(page.text, page.page_index)
    return _match_tier_from_lines(title, list(lines[: settings.top_of_page_line_limit]), settings)


def determine_anchor_local_match_tier(
    title: str,
    page: PageArtifacts,
    *,
    anchor_start_offset: int,
    settings: TreeSettings,
) -> TitleMatchTier:
    """Fallback verification tier around a mid-page heading anchor."""

    lines = split_text_lines_with_offsets(page.text, page.page_index)
    if not lines:
        return TitleMatchTier.NONE
    anchor_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.start_offset <= anchor_start_offset < line.end_offset
        ),
        len(lines) - 1,
    )
    return _match_tier_from_lines(
        title,
        list(lines[max(0, anchor_index - 2) : anchor_index + 3]),
        settings,
    )


def _bounded_page_excerpt(page: PageArtifacts, settings: TreeSettings) -> str:
    lines = split_text_lines_with_offsets(page.text, page.page_index)
    excerpt_lines = [line.text for line in lines[: settings.top_of_page_line_limit]]
    return "\n".join(excerpt_lines) if excerpt_lines else page.text[:400]


def _is_positive_verdict(value: str) -> bool:
    return value.strip().casefold() == "yes"


class LLMVerificationAssistant:
    """Opt-in verification assistant for deterministic title-matching misses."""

    def __init__(
        self,
        gateway: StructuredLLMGateway,
        artifact_root: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._artifact_root = artifact_root
        self._records: list[LLMVerificationAssistRecord] = []
        self._artifact_path: str | None = None

    @property
    def artifact_path(self) -> str | None:
        return self._artifact_path

    def assist(
        self,
        *,
        node: HierarchyNode,
        page: PageArtifacts,
        settings: TreeSettings,
    ) -> tuple[TitleMatchTier, LLMVerificationAssistRecord]:
        success = self._gateway.invoke(
            GatewayRequest[VerificationPromptResponse](
                operation_name="verify_heading_title",
                messages=build_verification_messages(
                    title=node.title,
                    page_excerpt=_bounded_page_excerpt(page, settings),
                    expected_span=(node.page_span.start_page, node.page_span.end_page),
                ),
                response_model=VerificationPromptResponse,
            )
        )
        response = success.output
        supporting_quotes = tuple(response.supporting_quotes)
        grounded_quotes = tuple(quote for quote in supporting_quotes if quote in page.text)
        ungrounded_quotes = tuple(quote for quote in supporting_quotes if quote not in page.text)
        accepted = _is_positive_verdict(response.verdict) and bool(grounded_quotes)
        record = LLMVerificationAssistRecord(
            node_id=node.node_id,
            title=node.title,
            page_index=page.page_index,
            llm_verdict=response.verdict,
            llm_rationale=response.rationale,
            supporting_quotes=supporting_quotes,
            grounded_quotes=grounded_quotes,
            ungrounded_quotes=ungrounded_quotes,
            accepted=accepted,
        )
        self._records.append(record)
        if self._artifact_root is not None:
            self._artifact_path = _write_json(
                Path(self._artifact_root) / "verify" / "llm-assists.json",
                tuple(self._records),
            )
        return (
            TitleMatchTier.LLM_VERIFIED if accepted else TitleMatchTier.NONE,
            record,
        )


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


def _child_span_is_valid(node: HierarchyNode, parent: HierarchyNode) -> bool:
    traditional_nesting = (
        parent.page_span.start_page
        <= node.page_span.start_page
        <= node.page_span.end_page
        <= parent.page_span.end_page
    )
    prefix_truncated_parent = (
        parent.page_span.start_page <= node.page_span.start_page
        and parent.page_span.end_page <= node.page_span.start_page
    )
    return traditional_nesting or prefix_truncated_parent


def _owned_span_is_valid(node: HierarchyNode, parent: HierarchyNode) -> bool:
    if not node.owned_spans or not parent.owned_spans:
        return _child_span_is_valid(node, parent)

    parent_spans = tuple(owned_span.span for owned_span in parent.owned_spans)
    child_spans = tuple(owned_span.span for owned_span in node.owned_spans)

    def _parent_contains_child(parent_span: ContentSpan, child_span: ContentSpan) -> bool:
        if (
            child_span.start_page < parent_span.start_page
            or child_span.end_page > parent_span.end_page
        ):
            return False
        if (
            child_span.start_page == parent_span.start_page
            and child_span.start_offset < parent_span.start_offset
        ):
            return False
        return not (
            child_span.end_page == parent_span.end_page
            and child_span.end_offset > parent_span.end_offset
        )

    def _parent_is_prefix_before_child(parent_span: ContentSpan, child_span: ContentSpan) -> bool:
        return parent_span.end_page < child_span.start_page or (
            parent_span.end_page == child_span.start_page
            and parent_span.end_offset <= child_span.start_offset
        )

    prefix_truncated_parent = all(
        _parent_is_prefix_before_child(parent_span, child_span)
        for parent_span in parent_spans
        for child_span in child_spans
    )
    if prefix_truncated_parent:
        return True
    return all(
        any(_parent_contains_child(parent_span, child_span) for parent_span in parent_spans)
        for child_span in child_spans
    )


def verify_hierarchy(
    *,
    document_id: str,
    tree_run_id: str,
    page_count: int,
    nodes: tuple[HierarchyNode, ...],
    pages: tuple[PageArtifacts, ...],
    unassigned_spans: tuple[UnassignedPageSpan, ...],
    settings: TreeSettings,
    verification_assistant: LLMVerificationAssistant | None = None,
    outline_anchor_records: tuple[OutlineAnchorRecord, ...] = (),
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
            assist_record: LLMVerificationAssistRecord | None = None
            match_tier = determine_title_match_tier(node.title, page, settings)
            if match_tier == TitleMatchTier.NONE and node.heading_anchor.start_offset > 0:
                match_tier = determine_anchor_local_match_tier(
                    node.title,
                    page,
                    anchor_start_offset=node.heading_anchor.start_offset,
                    settings=settings,
                )
            if match_tier == TitleMatchTier.NONE and verification_assistant is not None:
                match_tier, assist_record = verification_assistant.assist(
                    node=node,
                    page=page,
                    settings=settings,
                )
            if match_tier == TitleMatchTier.NONE:
                issue_code = "page-present-but-title-not-visible"
                issue_message = "node title is not visible in bounded physical page text"
                if (
                    assist_record is not None
                    and _is_positive_verdict(assist_record.llm_verdict)
                    and not assist_record.grounded_quotes
                ):
                    issue_code = "llm-claimed-but-ungrounded"
                    issue_message = (
                        "verification assistant claimed support without grounded source quotes"
                    )
                issues.append(
                    VerificationIssue(
                        code=issue_code,
                        message=issue_message,
                        severity=VerificationSeverity.ERROR,
                        page_span=node.page_span,
                    ),
                )

        parent = nodes_by_id.get(node.parent_id) if node.parent_id is not None else None
        if parent is not None and not _owned_span_is_valid(node, parent):
            issues.append(
                VerificationIssue(
                    code="child-outside-parent-span",
                    message="child node owned span must remain inside its parent owned span",
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
    for record in outline_anchor_records:
        if record.status is OutlineAnchorStatus.ANCHORED_TO_PHYSICAL_TEXT:
            continue
        if record.status is OutlineAnchorStatus.OUTLINE_KNOWN_BUT_UNANCHORED:
            issue_code = (
                "page-present-but-title-not-visible"
                if record.reason == "page_present_but_title_not_visible"
                else "outline-known-but-unanchored"
            )
            issue_message = (
                "outline entry is known but could not be anchored to physical text"
                if issue_code == "outline-known-but-unanchored"
                else "outline entry points to a page where the title is not physically visible"
            )
        else:
            issue_code = "outline-entry-rejected"
            issue_message = record.reason or "outline entry could not be used for anchoring"
        page_span = (
            PageSpan(start_page=record.page_index, end_page=record.page_index)
            if record.page_index is not None
            else None
        )
        document_issues.append(
            VerificationIssue(
                code=issue_code,
                message=issue_message,
                severity=VerificationSeverity.WARNING,
                page_span=page_span,
            )
        )

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
    has_document_error = any(
        issue.severity == VerificationSeverity.ERROR for issue in document_issues
    )
    report_status = (
        VerificationStatus.FAILED
        if has_node_failure or has_document_error
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
