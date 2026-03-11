"""Unit tests for deterministic Phase 02 tree pipeline helpers."""

from __future__ import annotations

from typing import Any

from strataforge.domain.models import (
    AnchorSource,
    HeadingCandidate,
    HeadingScoreBreakdown,
    HeadingSourceKind,
    NodeAnchor,
    OutlineEntry,
    OutlineQualityReport,
    OutlineSource,
    OutlineTrustMode,
    RepairDecision,
    RepairKind,
    RepairRequest,
    RepairStatus,
    TreeSettings,
)
from strataforge.tree.headings import (
    PageArtifacts,
    extract_inferred_candidates,
    extract_outline_candidates,
    find_repeated_header_footer_lines,
    normalized_title_key,
    split_text_lines_with_offsets,
)
from strataforge.tree.hierarchy import (
    build_hierarchy,
    determine_outline_trust_mode,
    generate_node_id,
)
from strataforge.tree.repair import NoopRepairEngine
from strataforge.tree.verify import determine_title_match_tier


def make_settings() -> TreeSettings:
    return TreeSettings()


def make_anchor(page: int, start_offset: int, text: str) -> NodeAnchor:
    return NodeAnchor(
        page=page,
        start_offset=start_offset,
        end_offset=start_offset + len(text),
        anchor_text=text,
        anchor_source=AnchorSource.TEXT,
        occurrence_index=0,
    )


def make_candidate(title: str, page_index: int) -> HeadingCandidate:
    return HeadingCandidate(
        document_id="f" * 64,
        page_index=page_index,
        title=title,
        normalized_title=normalized_title_key(title),
        anchor=make_anchor(page_index, 0, title),
        source_kind=HeadingSourceKind.TEXT,
        level_hint=None,
        outline_level_hint=None,
        score_breakdown=HeadingScoreBreakdown(
            numbering_signal=22,
            isolation_signal=12,
            short_line_signal=14,
            title_case_signal=10,
            final_score=58,
        ),
        keep=True,
        high_confidence=True,
    )


def rawdict_for_text(text: str) -> dict[str, Any]:
    lines = [line for line in text.splitlines() if line.strip()]
    return {
        "blocks": [
            {
                "type": 0,
                "bbox": [72.0, 72.0, 540.0, 200.0],
                "lines": [
                    {
                        "bbox": [72.0, 72.0 + index * 24.0, 300.0, 90.0 + index * 24.0],
                        "spans": [
                            {
                                "size": 18.0 if index == 0 else 11.0,
                                "text": line,
                                "chars": [{"c": char} for char in line],
                            }
                        ],
                    }
                    for index, line in enumerate(lines)
                ],
            }
        ]
    }


def test_split_text_lines_preserves_nth_occurrence_offsets() -> None:
    lines = split_text_lines_with_offsets("Intro\nBody\nIntro", page_index=0)
    intro_lines = [line for line in lines if line.normalized_text == normalized_title_key("Intro")]

    assert [line.occurrence_index for line in intro_lines] == [0, 1]
    assert [line.start_offset for line in intro_lines] == [0, 11]


def test_split_text_lines_preserves_literal_spacing_in_offsets() -> None:
    text = "Control  Room\nBody\nControl Room"
    lines = split_text_lines_with_offsets(text, page_index=0)
    control_lines = [
        line for line in lines if line.normalized_text == normalized_title_key("Control Room")
    ]

    assert [line.text for line in control_lines] == ["Control  Room", "Control Room"]
    assert [line.occurrence_index for line in control_lines] == [0, 1]
    assert [text[line.start_offset : line.end_offset] for line in control_lines] == [
        "Control  Room",
        "Control Room",
    ]


def test_extract_outline_candidates_anchors_duplicate_titles_by_nth_occurrence() -> None:
    page = PageArtifacts(
        page_index=0,
        text="Control  Room\nBody\nControl Room",
        rawdict=None,
    )
    entries = (
        OutlineEntry(level=1, title="Control Room", page_index=0, source=OutlineSource.PYMUPDF),
        OutlineEntry(level=1, title="Control Room", page_index=0, source=OutlineSource.PYMUPDF),
    )

    candidates = extract_outline_candidates(
        document_id="a" * 64,
        pages=(page,),
        outline_entries=entries,
    )

    assert [candidate.anchor.occurrence_index for candidate in candidates] == [0, 1]
    assert [candidate.anchor.start_offset for candidate in candidates] == [0, 19]
    assert [candidate.anchor.anchor_text for candidate in candidates] == [
        "Control  Room",
        "Control Room",
    ]


def test_extract_inferred_candidates_prefers_rawdict_line_grouping() -> None:
    page = PageArtifacts(
        page_index=0,
        text="Scope\nBoundary notes.",
        rawdict=rawdict_for_text("Scope\nBoundary notes."),
    )

    candidates = extract_inferred_candidates(
        document_id="a" * 64,
        pages=(page,),
        outline_entries=(),
        settings=make_settings(),
    )
    scope_candidate = next(candidate for candidate in candidates if candidate.title == "Scope")

    assert scope_candidate.source_kind is HeadingSourceKind.RAWDICT
    assert scope_candidate.anchor.anchor_source.value == "rawdict"
    assert scope_candidate.score_breakdown.layout_cues_available is True


def test_repeated_header_footer_lines_are_detected_and_suppressed() -> None:
    pages = (
        PageArtifacts(page_index=0, text="ACME SPECIFICATION\n1 Safety\nBody.", rawdict=None),
        PageArtifacts(page_index=1, text="ACME SPECIFICATION\n2 Maintenance\nBody.", rawdict=None),
        PageArtifacts(page_index=2, text="ACME SPECIFICATION\n3 Appendix\nBody.", rawdict=None),
    )

    repeated = find_repeated_header_footer_lines(pages, make_settings())
    candidates = extract_inferred_candidates(
        document_id="b" * 64,
        pages=pages,
        outline_entries=(),
        settings=make_settings(),
    )

    assert normalized_title_key("ACME SPECIFICATION") in repeated
    assert not any(
        candidate.title == "ACME SPECIFICATION" and candidate.keep for candidate in candidates
    )


def test_build_hierarchy_uses_numbering_levels() -> None:
    candidates = (
        make_candidate("1 Root", 0),
        make_candidate("1.1 Child", 1),
        make_candidate("2 Next", 2),
    )

    nodes, repair_requests, ambiguity_count = build_hierarchy(
        document_id="c" * 64,
        candidates=candidates,
        page_count=3,
        trust_mode=OutlineTrustMode.INFERRED_PRIMARY,
    )

    assert [node.level for node in nodes] == [1, 2, 1]
    assert not repair_requests
    assert ambiguity_count == 0


def test_determine_outline_trust_mode_uses_tree_settings_thresholds() -> None:
    outline_candidates = (make_candidate("1 Root", 0),)
    inferred_candidates = (
        make_candidate("1 Root", 0),
        make_candidate("2 Different", 1),
    )
    reports = (
        OutlineQualityReport(
            source=OutlineSource.PYMUPDF,
            entry_count=1,
            null_destination_count=0,
            empty_title_count=0,
            non_monotonic_count=0,
            invalid_level_count=0,
            max_depth=1,
            score=100,
        ),
    )

    trust_mode = determine_outline_trust_mode(
        selected_source=OutlineSource.PYMUPDF,
        outline_reports=reports,
        outline_candidates=outline_candidates,
        inferred_candidates=inferred_candidates,
        settings=make_settings(),
    )

    assert trust_mode is OutlineTrustMode.HYBRID


def test_determine_title_match_tier_uses_precise_match_order() -> None:
    settings = make_settings()

    exact_page = PageArtifacts(page_index=0, text="Overview\nBody.", rawdict=None)
    punct_page = PageArtifacts(page_index=0, text="Overview!\nBody.", rawdict=None)
    token_page = PageArtifacts(page_index=0, text="Control Valve Details\nBody.", rawdict=None)
    edit_page = PageArtifacts(page_index=0, text="Operations\nBody.", rawdict=None)

    assert determine_title_match_tier("Overview", exact_page, settings).value == "exact_normalized"
    assert determine_title_match_tier("Overview", punct_page, settings).value == "casefold_punct"
    assert (
        determine_title_match_tier("Control Valve", token_page, settings).value
        == "token_containment"
    )
    assert determine_title_match_tier("Operatons", edit_page, settings).value == "edit_distance"


def test_generate_node_id_is_stable() -> None:
    first = generate_node_id(
        document_id="d" * 64,
        path=("Root", "Child"),
        level=2,
        page=3,
        start_offset=10,
        end_offset=20,
        span_start_page=3,
    )
    second = generate_node_id(
        document_id="d" * 64,
        path=("Root", "Child"),
        level=2,
        page=3,
        start_offset=10,
        end_offset=20,
        span_start_page=3,
    )

    assert first == second


def test_noop_repair_engine_and_repair_status_models() -> None:
    request = RepairRequest(
        request_id="request-001",
        subject_id="subject-001",
        repair_kind=RepairKind.PARTIAL_TOC_REPAIR,
        rationale="outline coverage is incomplete",
    )
    decisions = NoopRepairEngine().evaluate((request,))
    sentinel = RepairDecision(
        subject_id="document-001",
        status=RepairStatus.NOT_REQUESTED,
        message="no repair work was needed",
    )

    assert decisions[0].status is RepairStatus.NOOP_APPLIED
    assert decisions[0].repair_kind is RepairKind.PARTIAL_TOC_REPAIR
    assert sentinel.status is RepairStatus.NOT_REQUESTED
