CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS vectordb;
DROP TABLE IF EXISTS vectordb.policy_docs CASCADE;

CREATE TABLE vectordb.policy_docs (
    doc_id TEXT PRIMARY KEY,

    page_content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    questions_embedding vector(1536),  -- keep NULL-able for backfill/migration

    -- First-class, indexable fields
    lang TEXT NOT NULL,              -- 'en' | 'ar'
    source TEXT NOT NULL,            -- filename
    page INT NOT NULL,
    page_column TEXT NOT NULL,            -- left | right | full
    pair_id TEXT NOT NULL,
    chunk_index INT NOT NULL,

    questions TEXT[] NOT NULL,        -- always populated

    metadata JSONB,

    ingest_dir TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);

-- CREATE INDEX IF NOT EXISTS policy_docs_lang_idx       ON vectordb.policy_docs(lang);
-- CREATE INDEX IF NOT EXISTS policy_docs_source_idx     ON vectordb.policy_docs(source);
-- CREATE INDEX IF NOT EXISTS policy_docs_title_idx      ON vectordb.policy_docs(title);
-- CREATE INDEX IF NOT EXISTS policy_docs_page_idx       ON vectordb.policy_docs(page);
-- CREATE INDEX IF NOT EXISTS policy_docs_pair_id_idx    ON vectordb.policy_docs(pair_id);
-- CREATE INDEX IF NOT EXISTS policy_docs_ingest_dir_idx ON vectordb.policy_docs(ingest_dir);



CREATE TABLE vectordb.transaction_embeddings (
    tx_id UUID PRIMARY KEY REFERENCES core.transactions(tx_id),
    embedding vector(1536),
    metadata JSONB
);


DROP TABLE IF EXISTS vectordb.policy_docs_test;

CREATE TABLE vectordb.policy_docs_test (
    doc_id TEXT PRIMARY KEY,
    page_content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    metadata JSONB
);
