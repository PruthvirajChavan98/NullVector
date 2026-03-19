CREATE TABLE IF NOT EXISTS document_description_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    artifact_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    identity JSONB NOT NULL,
    manifest_ref TEXT,
    manifest JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_selection_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    artifact_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    identity JSONB NOT NULL,
    manifest_ref TEXT,
    manifest JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tree_search_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    artifact_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    identity JSONB NOT NULL,
    manifest_ref TEXT,
    manifest JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tree_compaction_runs (
    run_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    artifact_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    identity JSONB NOT NULL,
    manifest_ref TEXT,
    manifest JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
