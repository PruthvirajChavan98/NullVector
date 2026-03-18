"""Unit coverage for PostgreSQL metadata clause compilation."""

from __future__ import annotations

from nullvector.domain.document_selection import DocumentFilterClause
from nullvector.storage.postgres import _metadata_clause_sql


def test_metadata_clause_sql_compiles_contains_filters() -> None:
    clause = DocumentFilterClause(field="company", operator="contains", value="Acme")

    sql, params = _metadata_clause_sql(clause)

    assert "jsonb_typeof(attributes -> %s) = 'string'" in sql
    assert "lower(attributes ->> %s) LIKE %s" in sql
    assert params == ["company", "company", "company", "%acme%"]


def test_metadata_clause_sql_compiles_in_filters_with_jsonb_values() -> None:
    clause = DocumentFilterClause(field="year", operator="in", value=(2023, 2024))

    sql, params = _metadata_clause_sql(clause)

    assert "attributes ? %s" in sql
    assert "attributes -> %s = %s::jsonb" in sql
    assert params == ["year", "year", "2023", "year", "2024"]
