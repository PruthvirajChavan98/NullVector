"""Regression coverage for retrieval planning helpers."""

from __future__ import annotations

from nullvector.retrieval.planner import QueryPlanner


def test_query_planner_dedupes_repeated_titles_without_runtime_name_errors() -> None:
    plan = QueryPlanner().plan('section "Overview" and "Overview" on page 2')

    assert plan.page_filter is not None
    assert plan.page_filter.start_page == 1
    assert plan.page_filter.end_page == 1
    assert plan.quoted_phrases == ("overview",)
    assert any("overview" in phrase for phrase in plan.title_like_phrases)
