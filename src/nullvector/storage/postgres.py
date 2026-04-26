"""PostgreSQL-backed implementation of the shared DocumentStore protocol."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from importlib.resources import files as _resource_files
from typing import Any, cast

from pydantic import BaseModel

from nullvector.domain.document_selection import (
    DocumentFilterClause,
    DocumentFilterOperator,
    DocumentMetadataRecord,
)
from nullvector.domain.ledger import DocumentFingerprint
from nullvector.storage._serialization import (
    build_postgres_artifact_ref,
    build_postgres_binary_ref,
    canonical_json_text,
    json_safe,
    parse_postgres_ref,
)
from nullvector.storage.config import StorageBackend
from nullvector.storage.protocol import RunScopedStore, ScopedDocumentRun

try:  # pragma: no cover - exercised in integration environments with postgres extra installed
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    psycopg = None  # type: ignore[assignment]  # optional dependency not installed
    dict_row = None  # type: ignore[assignment]  # optional dependency not installed

# ---------------------------------------------------------------------------
# Schema migration registry
# ---------------------------------------------------------------------------

# Append new version names here; never modify or remove existing entries.
_MIGRATION_VERSIONS: tuple[str, ...] = (
    "001_initial",
    "002_document_metadata",
    "003_run_tables_phase_fj",
)
_SCHEMA_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_schema_name(schema: str) -> str:
    """Validate one PostgreSQL schema identifier before SQL interpolation."""

    if _SCHEMA_NAME_PATTERN.fullmatch(schema) is None:
        msg = "PostgreSQL schema names must match ^[A-Za-z_][A-Za-z0-9_]*$"
        raise ValueError(msg)
    return schema


def _escape_like_value(value: str) -> str:
    """Escape LIKE metacharacters for literal substring searches."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _pending_migrations(applied: frozenset[str]) -> list[tuple[str, str]]:
    """Return (version, sql) for every unapplied migration in declaration order.

    Args:
        applied: Set of version strings already recorded in schema_migrations.

    Returns:
        Ordered list of (version, sql) pairs not yet applied.
    """
    pkg = _resource_files("nullvector.storage.migrations")
    result: list[tuple[str, str]] = []
    for version in _MIGRATION_VERSIONS:
        if version not in applied:
            sql = pkg.joinpath(f"{version}.sql").read_text(encoding="utf-8")
            result.append((version, sql))
    return result


def _metadata_clause_sql(clause: DocumentFilterClause) -> tuple[str, list[Any]]:
    """Compile one typed metadata filter clause into PostgreSQL SQL + params."""

    field = clause.field
    if clause.operator is DocumentFilterOperator.EQ:
        return (
            "(attributes ? %s AND attributes -> %s = %s::jsonb)",
            [field, field, canonical_json_text(clause.value)],
        )
    if clause.operator is DocumentFilterOperator.IN:
        if not isinstance(clause.value, tuple):
            msg = "in filters require a tuple value"
            raise TypeError(msg)
        comparisons = " OR ".join("attributes -> %s = %s::jsonb" for _ in clause.value)
        params: list[Any] = [field]
        for item in clause.value:
            params.extend([field, canonical_json_text(item)])
        return (f"(attributes ? %s AND ({comparisons}))", params)
    if clause.operator is DocumentFilterOperator.CONTAINS:
        return (
            "("
            "attributes ? %s "
            "AND jsonb_typeof(attributes -> %s) = 'string' "
            "AND lower(attributes ->> %s) LIKE %s ESCAPE '\\'"
            ")",
            [
                field,
                field,
                field,
                f"%{_escape_like_value(cast(str, clause.value).casefold())}%",
            ],
        )
    comparator = ">=" if clause.operator is DocumentFilterOperator.GTE else "<="
    return (
        "("
        "attributes ? %s "
        "AND jsonb_typeof(attributes -> %s) = 'number' "
        f"AND (attributes ->> %s)::double precision {comparator} %s"
        ")",
        [field, field, field, float(cast(int | float, clause.value))],
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class PostgresDependencyError(RuntimeError):
    """Raised when the PostgreSQL storage backend is used without psycopg installed."""


class PostgresDocumentStore:
    """PostgreSQL persistence using sync psycopg and JSONB payloads."""

    backend = StorageBackend.POSTGRES

    def __init__(self, conninfo: str, *, schema: str = "public") -> None:
        if psycopg is None or dict_row is None:
            msg = "PostgreSQL storage requires the optional 'psycopg[binary]' dependency"
            raise PostgresDependencyError(msg)
        self._conninfo = conninfo
        self._schema = _validate_schema_name(schema)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Apply any pending schema migrations idempotently.

        Uses a PostgreSQL transaction-level advisory lock so concurrent workers
        (e.g. multiple processes starting simultaneously) serialize safely.
        All DDL and version tracking execute inside a single transaction —
        either everything is applied or nothing is.
        """
        with self._connect() as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            # Acquire a transaction-level advisory lock keyed to this schema.
            # pg_advisory_xact_lock blocks until the lock is available and
            # releases automatically when the transaction commits or rolls back.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"nullvector:schema_v1:{self._schema}",),
            )
            conn.execute(f"SET LOCAL search_path TO {self._schema}")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._schema}.schema_migrations (
                    version    TEXT        PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            applied: frozenset[str] = frozenset(
                row["version"]
                for row in conn.execute(
                    f"SELECT version FROM {self._schema}.schema_migrations"
                ).fetchall()
            )
            for version, sql in _pending_migrations(applied):
                conn.execute(sql)
                conn.execute(
                    f"INSERT INTO {self._schema}.schema_migrations (version) VALUES (%s)",
                    (version,),
                )

    @property
    def supports_metadata_persistence(self) -> bool:
        return True

    @property
    def supports_retrieval_unit_queries(self) -> bool:
        return True

    def resolve_artifact_root(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        configured_root: str | None = None,
    ) -> str | None:
        del run_type, run_id, document_id, configured_root
        return None

    def register_document(self, fingerprint: DocumentFingerprint) -> str:
        data = fingerprint.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.documents (
                    document_id,
                    source_path,
                    sha256,
                    file_size_bytes,
                    page_count,
                    fingerprint
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (document_id) DO NOTHING
                """,
                (
                    data["document_id"],
                    data["source_path"],
                    data["sha256"],
                    data["file_size_bytes"],
                    data["page_count"],
                    canonical_json_text(fingerprint),
                ),
            )
        return fingerprint.document_id

    def reserve_run(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_root: str | None = None,
        identity: Mapping[str, object | None],
    ) -> tuple[bool, dict[str, Any]]:
        table = self._run_table(run_type)
        # Postgres runs store "" when artifact_root is None
        # (convention: all *_runs tables use NOT NULL).
        _root = artifact_root or ""
        with self._connect() as conn:
            inserted = conn.execute(
                f"""
                INSERT INTO {self._schema}.{table} (
                    run_id,
                    document_id,
                    artifact_root,
                    status,
                    identity,
                    manifest_ref
                )
                VALUES (%s, %s, %s, 'running', %s::jsonb, NULL)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (run_id, document_id, _root, canonical_json_text(identity)),
            )
            created = inserted.rowcount > 0
            row = conn.execute(
                f"""
                SELECT
                    run_id,
                    document_id,
                    artifact_root,
                    status,
                    identity,
                    manifest_ref
                FROM {self._schema}.{table}
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            msg = f"failed to reserve run {run_type}:{run_id}"
            raise RuntimeError(msg)
        return created, dict(row)

    def complete_run(
        self,
        *,
        run_type: str,
        run_id: str,
        manifest_ref: str,
        manifest: BaseModel,
    ) -> None:
        table = self._run_table(run_type)
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE {self._schema}.{table}
                SET status = 'succeeded',
                    manifest_ref = %s,
                    manifest = %s::jsonb
                WHERE run_id = %s
                """,
                (manifest_ref, canonical_json_text(manifest), run_id),
            )

    def for_run(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
    ) -> RunScopedStore:
        return ScopedDocumentRun(self, run_type=run_type, run_id=run_id, document_id=document_id)

    def artifact_ref(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_path: str,
    ) -> str:
        return build_postgres_artifact_ref(
            run_type=run_type,
            run_id=run_id,
            document_id=document_id,
            artifact_path=artifact_path,
        )

    def binary_asset_ref(
        self,
        *,
        run_id: str,
        document_id: str,
        asset_path: str,
    ) -> str:
        return build_postgres_binary_ref(
            run_id=run_id,
            document_id=document_id,
            asset_path=asset_path,
        )

    def put_json_artifact(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_kind: str,
        artifact_path: str,
        payload: Any,
    ) -> str:
        ref = self.artifact_ref(
            run_type=run_type,
            run_id=run_id,
            document_id=document_id,
            artifact_path=artifact_path,
        )
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.artifacts (
                    run_type,
                    run_id,
                    document_id,
                    artifact_kind,
                    artifact_path,
                    encoding,
                    payload,
                    text_payload
                )
                VALUES (%s, %s, %s, %s, %s, 'json', %s::jsonb, NULL)
                ON CONFLICT (run_type, run_id, document_id, artifact_path)
                DO UPDATE SET artifact_kind = EXCLUDED.artifact_kind, payload = EXCLUDED.payload
                """,
                (
                    run_type,
                    run_id,
                    document_id,
                    artifact_kind,
                    artifact_path,
                    canonical_json_text(payload),
                ),
            )
        return ref

    def put_jsonl_artifact(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_kind: str,
        artifact_path: str,
        payloads: Sequence[Any],
    ) -> str:
        ref = self.artifact_ref(
            run_type=run_type,
            run_id=run_id,
            document_id=document_id,
            artifact_path=artifact_path,
        )
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.artifacts (
                    run_type,
                    run_id,
                    document_id,
                    artifact_kind,
                    artifact_path,
                    encoding,
                    payload,
                    text_payload
                )
                VALUES (%s, %s, %s, %s, %s, 'jsonl', %s::jsonb, NULL)
                ON CONFLICT (run_type, run_id, document_id, artifact_path)
                DO UPDATE SET artifact_kind = EXCLUDED.artifact_kind, payload = EXCLUDED.payload
                """,
                (
                    run_type,
                    run_id,
                    document_id,
                    artifact_kind,
                    artifact_path,
                    canonical_json_text(payloads),
                ),
            )
        return ref

    def put_text_artifact(
        self,
        *,
        run_type: str,
        run_id: str,
        document_id: str,
        artifact_kind: str,
        artifact_path: str,
        content: str,
    ) -> str:
        ref = self.artifact_ref(
            run_type=run_type,
            run_id=run_id,
            document_id=document_id,
            artifact_path=artifact_path,
        )
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.artifacts (
                    run_type,
                    run_id,
                    document_id,
                    artifact_kind,
                    artifact_path,
                    encoding,
                    payload,
                    text_payload
                )
                VALUES (%s, %s, %s, %s, %s, 'text', NULL, %s)
                ON CONFLICT (run_type, run_id, document_id, artifact_path)
                DO UPDATE SET
                    artifact_kind = EXCLUDED.artifact_kind,
                    text_payload = EXCLUDED.text_payload
                """,
                (run_type, run_id, document_id, artifact_kind, artifact_path, content),
            )
        return ref

    def put_binary_asset(
        self,
        *,
        run_id: str,
        document_id: str,
        asset_path: str,
        content_type: str,
        data: bytes,
    ) -> str:
        ref = self.binary_asset_ref(
            run_id=run_id,
            document_id=document_id,
            asset_path=asset_path,
        )
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.binary_assets (
                    run_id,
                    document_id,
                    asset_path,
                    content_type,
                    data
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (run_id, document_id, asset_path)
                DO UPDATE SET content_type = EXCLUDED.content_type, data = EXCLUDED.data
                """,
                (run_id, document_id, asset_path, content_type, data),
            )
        return ref

    def read_json_artifact(self, ref: str) -> Any:
        run_type, run_id, document_id, artifact_path = parse_postgres_ref(ref)
        if run_type == "__binary__":
            msg = f"binary ref cannot be loaded as JSON: {ref}"
            raise ValueError(msg)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT payload
                FROM {self._schema}.artifacts
                WHERE run_type = %s AND run_id = %s AND document_id = %s AND artifact_path = %s
                """,
                (run_type, run_id, document_id, artifact_path),
            ).fetchone()
        if row is None:
            msg = f"artifact not found: {ref}"
            raise FileNotFoundError(msg)
        return row["payload"]

    def read_jsonl_artifact(self, ref: str) -> tuple[Any, ...]:
        payload = self.read_json_artifact(ref)
        if not isinstance(payload, list):
            msg = f"jsonl artifact does not contain a JSON array payload: {ref}"
            raise ValueError(msg)
        return tuple(payload)

    def read_text_artifact(self, ref: str) -> str:
        run_type, run_id, document_id, artifact_path = parse_postgres_ref(ref)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT text_payload
                FROM {self._schema}.artifacts
                WHERE run_type = %s AND run_id = %s AND document_id = %s AND artifact_path = %s
                """,
                (run_type, run_id, document_id, artifact_path),
            ).fetchone()
        if row is None or row["text_payload"] is None:
            msg = f"text artifact not found: {ref}"
            raise FileNotFoundError(msg)
        return cast(str, row["text_payload"])

    def read_binary_asset(self, ref: str) -> bytes:
        prefix, run_id, document_id, asset_path = parse_postgres_ref(ref)
        if prefix != "__binary__":
            msg = f"artifact ref is not a binary asset: {ref}"
            raise ValueError(msg)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT data
                FROM {self._schema}.binary_assets
                WHERE run_id = %s AND document_id = %s AND asset_path = %s
                """,
                (run_id, document_id, asset_path),
            ).fetchone()
        if row is None:
            msg = f"binary asset not found: {ref}"
            raise FileNotFoundError(msg)
        return cast(bytes, row["data"])

    def put_retrieval_units(
        self,
        document_id: str,
        units: tuple[BaseModel, ...],
    ) -> int:
        with self._connect() as conn, conn.cursor() as cursor:
            for unit in units:
                data = unit.model_dump(mode="json")
                cursor.execute(
                    f"""
                        INSERT INTO {self._schema}.retrieval_units (
                            unit_id,
                            document_id,
                            unit_type,
                            modality,
                            start_page,
                            end_page,
                            node_id,
                            title,
                            text_content,
                            keywords,
                            authoritative,
                            interpretive,
                            trust_tier,
                            payload
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (document_id, unit_id)
                        DO UPDATE SET
                            unit_type = EXCLUDED.unit_type,
                            modality = EXCLUDED.modality,
                            start_page = EXCLUDED.start_page,
                            end_page = EXCLUDED.end_page,
                            node_id = EXCLUDED.node_id,
                            title = EXCLUDED.title,
                            text_content = EXCLUDED.text_content,
                            keywords = EXCLUDED.keywords,
                            authoritative = EXCLUDED.authoritative,
                            interpretive = EXCLUDED.interpretive,
                            trust_tier = EXCLUDED.trust_tier,
                            payload = EXCLUDED.payload
                        """,
                    (
                        data["unit_id"],
                        document_id,
                        data["unit_type"],
                        data["modality"],
                        data["page_span"]["start_page"],
                        data["page_span"]["end_page"],
                        data.get("node_id"),
                        data.get("title"),
                        data.get("text"),
                        list(data.get("keywords", [])),
                        data.get("authoritative", False),
                        data.get("interpretive", False),
                        data.get("trust_tier"),
                        canonical_json_text(unit),
                    ),
                )
        return len(units)

    def query_retrieval_units(
        self,
        document_id: str,
        *,
        page_start: int | None = None,
        page_end: int | None = None,
        unit_types: tuple[str, ...] = (),
        modalities: tuple[str, ...] = (),
        text_query: str | None = None,
        limit: int | None = 50,
    ) -> list[dict[str, Any]]:
        conditions = ["document_id = %s"]
        params: list[Any] = [document_id]
        if page_start is not None and page_end is not None:
            conditions.append("start_page <= %s AND end_page >= %s")
            params.extend([page_end, page_start])
        if unit_types:
            conditions.append("unit_type = ANY(%s)")
            params.append(list(unit_types))
        if modalities:
            conditions.append("modality = ANY(%s)")
            params.append(list(modalities))
        if text_query:
            conditions.append(
                "to_tsvector('english'::regconfig, coalesce(title, '') || ' ' || "
                "coalesce(text_content, '') || ' ' || nullvector_array_to_text(keywords)) "
                "@@ plainto_tsquery('english'::regconfig, %s)"
            )
            params.append(text_query)
        query = f"""
            SELECT payload
            FROM {self._schema}.retrieval_units
            WHERE {" AND ".join(conditions)}
            ORDER BY start_page ASC, end_page ASC, lower(coalesce(title, '')) ASC, unit_id ASC
        """
        if limit is not None:
            query = f"{query}\n            LIMIT %s"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [cast(dict[str, Any], row["payload"]) for row in rows]

    def put_metadata_records(
        self,
        collection_id: str,
        records: Sequence[DocumentMetadataRecord],
    ) -> int:
        with self._connect() as conn, conn.cursor() as cursor:
            for record in records:
                payload = record.model_dump(mode="json")
                cursor.execute(
                    f"""
                        INSERT INTO {self._schema}.document_metadata_records (
                            collection_id,
                            document_id,
                            display_name,
                            attributes,
                            payload
                        )
                        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (collection_id, document_id)
                        DO UPDATE SET
                            display_name = EXCLUDED.display_name,
                            attributes = EXCLUDED.attributes,
                            payload = EXCLUDED.payload,
                            updated_at = now()
                        """,
                    (
                        collection_id,
                        record.document_id,
                        record.display_name,
                        canonical_json_text(record.attributes),
                        canonical_json_text(payload),
                    ),
                )
        return len(records)

    def load_metadata_records(self, collection_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT payload
                FROM {self._schema}.document_metadata_records
                WHERE collection_id = %s
                ORDER BY lower(display_name), document_id
                """,
                (collection_id,),
            ).fetchall()
        return [cast(dict[str, Any], row["payload"]) for row in rows]

    def query_metadata_records(
        self,
        collection_id: str,
        *,
        clauses: tuple[DocumentFilterClause, ...] = (),
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conditions = ["collection_id = %s"]
        params: list[Any] = [collection_id]
        for clause in clauses:
            sql, clause_params = _metadata_clause_sql(clause)
            conditions.append(sql)
            params.extend(clause_params)
        params.append(limit)
        query = f"""
            SELECT payload
            FROM {self._schema}.document_metadata_records
            WHERE {" AND ".join(conditions)}
            ORDER BY lower(display_name), document_id
            LIMIT %s
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [cast(dict[str, Any], row["payload"]) for row in rows]

    def append_audit(self, record: BaseModel) -> str | None:
        payload = record.model_dump(mode="json")
        document_id = payload.get("metadata", {}).get("document_id")
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.gateway_audit_log (
                    audit_id,
                    request_id,
                    operation_name,
                    provider_name,
                    model_name,
                    document_id,
                    status,
                    failure_category,
                    record
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (audit_id) DO UPDATE SET record = EXCLUDED.record
                """,
                (
                    payload["audit_id"],
                    payload["request_id"],
                    payload["operation_name"],
                    payload["provider_name"],
                    payload["model_name"],
                    document_id,
                    "failure" if payload.get("failure") is not None else "success",
                    (payload.get("failure") or {}).get("category"),
                    canonical_json_text(record),
                ),
            )
        return build_postgres_artifact_ref(
            run_type="audit",
            run_id=payload["request_id"],
            document_id=str(document_id or "global"),
            artifact_path=f"{payload['audit_id']}.json",
        )

    def append_event(self, event: BaseModel) -> None:
        payload = event.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.event_log (
                    event_id,
                    event_name,
                    document_id,
                    payload
                )
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (document_id, event_id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    payload["event_id"],
                    payload["event_name"],
                    payload["document_id"],
                    canonical_json_text(json_safe(event)),
                ),
            )

    def _connect(self) -> psycopg.Connection[Any]:
        if psycopg is None or dict_row is None:
            msg = "PostgreSQL storage requires the optional 'psycopg[binary]' dependency"
            raise PostgresDependencyError(msg)
        return psycopg.connect(self._conninfo, row_factory=dict_row)

    def _run_table(self, run_type: str) -> str:
        match run_type:
            case "parse":
                return "parse_runs"
            case "acquisition":
                return "acquisition_runs"
            case "tree":
                return "tree_runs"
            case "retrieval":
                return "retrieval_runs"
            case "document_description":
                return "document_description_runs"
            case "document_selection":
                return "document_selection_runs"
            case "tree_search":
                return "tree_search_runs"
            case "tree_compaction":
                return "tree_compaction_runs"
        msg = f"unsupported run type: {run_type}"
        raise ValueError(msg)


__all__ = ["PostgresDependencyError", "PostgresDocumentStore"]
