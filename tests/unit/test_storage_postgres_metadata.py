"""Unit coverage for PostgreSQL metadata clause compilation."""

from __future__ import annotations

import pytest

from nullvector.domain.document_selection import DocumentFilterClause, DocumentFilterOperator
from nullvector.storage.config import PostgresStorageConfig
from nullvector.storage.postgres import (
    PostgresDocumentStore,
    _metadata_clause_sql,
    _pending_migrations,
)


def test_metadata_clause_sql_compiles_contains_filters() -> None:
    clause = DocumentFilterClause(
        field="company",
        operator=DocumentFilterOperator.CONTAINS,
        value="Acme",
    )

    sql, params = _metadata_clause_sql(clause)

    assert "jsonb_typeof(attributes -> %s) = 'string'" in sql
    assert "lower(attributes ->> %s) LIKE %s ESCAPE '\\'" in sql
    assert params == ["company", "company", "company", "%acme%"]


def test_metadata_clause_sql_escapes_like_metacharacters() -> None:
    clause = DocumentFilterClause(
        field="name",
        operator=DocumentFilterOperator.CONTAINS,
        value=r"10%_off\deal",
    )

    sql, params = _metadata_clause_sql(clause)

    assert "ESCAPE '\\'" in sql
    assert params == ["name", "name", "name", r"%10\%\_off\\deal%"]


def test_metadata_clause_sql_compiles_in_filters_with_jsonb_values() -> None:
    clause = DocumentFilterClause(
        field="year",
        operator=DocumentFilterOperator.IN,
        value=(2023, 2024),
    )

    sql, params = _metadata_clause_sql(clause)

    assert "attributes ? %s" in sql
    assert "attributes -> %s = %s::jsonb" in sql
    assert params == ["year", "year", "2023", "year", "2024"]


@pytest.mark.parametrize("schema", ["public", "tenant_01", "_private"])
def test_postgres_storage_config_accepts_safe_schema_names(schema: str) -> None:
    config = PostgresStorageConfig(conninfo="postgresql://example/nullvector", schema=schema)

    assert config.pg_schema == schema


@pytest.mark.parametrize("schema", ["tenant-prod", "tenant prod", "tenant.prod", "9tenant"])
def test_postgres_storage_config_rejects_unsafe_schema_names(schema: str) -> None:
    with pytest.raises(ValueError, match="String should match pattern"):
        PostgresStorageConfig(conninfo="postgresql://example/nullvector", schema=schema)


def test_postgres_run_table_supports_current_feature_run_types() -> None:
    store = PostgresDocumentStore.__new__(PostgresDocumentStore)

    assert store._run_table("document_description") == "document_description_runs"
    assert store._run_table("document_selection") == "document_selection_runs"
    assert store._run_table("tree_search") == "tree_search_runs"
    assert store._run_table("tree_compaction") == "tree_compaction_runs"


def test_pending_migrations_include_phase_fj_run_tables() -> None:
    migrations = _pending_migrations(frozenset({"001_initial", "002_document_metadata"}))

    assert migrations[0][0] == "003_run_tables_phase_fj"
    sql = migrations[0][1]
    assert "CREATE TABLE IF NOT EXISTS document_description_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS document_selection_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS tree_search_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS tree_compaction_runs" in sql
