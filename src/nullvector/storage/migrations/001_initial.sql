-- IMMUTABLE wrapper required by PostgreSQL for use in index expressions.
-- array_to_string is STABLE in the system catalog because it can be
-- overloaded by custom element-to-text casts, but for text[] with a
-- constant delimiter it is genuinely deterministic.  Wrapping it in an
-- explicit IMMUTABLE SQL function is the canonical PostgreSQL solution.
CREATE OR REPLACE FUNCTION nullvector_array_to_text(text[])
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    STRICT
    PARALLEL SAFE
AS $$ SELECT array_to_string($1, ' ') $$;

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    page_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    fingerprint JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS parse_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    artifact_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    identity JSONB NOT NULL,
    manifest_ref TEXT,
    manifest JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS acquisition_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    artifact_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    identity JSONB NOT NULL,
    manifest_ref TEXT,
    manifest JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tree_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    artifact_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    identity JSONB NOT NULL,
    manifest_ref TEXT,
    manifest JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retrieval_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    artifact_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    identity JSONB NOT NULL,
    manifest_ref TEXT,
    manifest JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_type TEXT NOT NULL,
    run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    encoding TEXT NOT NULL,
    payload JSONB,
    text_payload TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_type, run_id, document_id, artifact_path)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts (run_type, run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_document ON artifacts (document_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON artifacts (artifact_kind);

CREATE TABLE IF NOT EXISTS binary_assets (
    asset_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    asset_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    data BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, document_id, asset_path)
);

CREATE TABLE IF NOT EXISTS retrieval_units (
    unit_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    modality TEXT NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    node_id TEXT,
    title TEXT,
    text_content TEXT,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    authoritative BOOLEAN NOT NULL DEFAULT FALSE,
    interpretive BOOLEAN NOT NULL DEFAULT FALSE,
    trust_tier TEXT,
    payload JSONB NOT NULL,
    PRIMARY KEY (document_id, unit_id)
);

CREATE INDEX IF NOT EXISTS idx_retrieval_page_range
    ON retrieval_units (document_id, start_page, end_page);
CREATE INDEX IF NOT EXISTS idx_retrieval_type_modality
    ON retrieval_units (document_id, unit_type, modality);
CREATE INDEX IF NOT EXISTS idx_retrieval_node
    ON retrieval_units (document_id, node_id) WHERE node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_retrieval_text
    ON retrieval_units USING GIN (
        to_tsvector(
            'english'::regconfig,
            coalesce(title, '') || ' ' || coalesce(text_content, '') || ' ' || nullvector_array_to_text(keywords)
        )
    );

CREATE TABLE IF NOT EXISTS gateway_audit_log (
    audit_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    operation_name TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    document_id TEXT,
    status TEXT NOT NULL,
    failure_category TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    record JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_request ON gateway_audit_log (request_id);
CREATE INDEX IF NOT EXISTS idx_audit_document
    ON gateway_audit_log (document_id) WHERE document_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_time ON gateway_audit_log (created_at);

CREATE TABLE IF NOT EXISTS event_log (
    event_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    document_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload JSONB NOT NULL,
    PRIMARY KEY (document_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_events_name ON event_log (event_name);
CREATE INDEX IF NOT EXISTS idx_events_time ON event_log (occurred_at);
