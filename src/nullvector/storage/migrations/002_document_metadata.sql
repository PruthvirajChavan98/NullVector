CREATE TABLE IF NOT EXISTS document_metadata_records (
    collection_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    attributes JSONB NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (collection_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_metadata_collection
    ON document_metadata_records (collection_id);

CREATE INDEX IF NOT EXISTS idx_document_metadata_display
    ON document_metadata_records (collection_id, lower(display_name), document_id);

CREATE INDEX IF NOT EXISTS idx_document_metadata_attributes
    ON document_metadata_records USING GIN (attributes);
