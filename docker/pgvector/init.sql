-- pgvector initial schema.
-- Stores the RAG corpus: synthetic runbooks + past-incident records the
-- LLM agent retrieves during reasoning.

CREATE EXTENSION IF NOT EXISTS vector;

-- =========================================================================
-- KNOWLEDGE_DOCS — runbooks, KB articles, past incidents
-- =========================================================================
CREATE TABLE IF NOT EXISTS knowledge_docs (
    doc_id           TEXT PRIMARY KEY,
    source           TEXT NOT NULL,             -- 'runbook', 'kb_article', 'past_incident'
    title            TEXT NOT NULL,
    content          TEXT NOT NULL,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- 384 = sentence-transformers/all-MiniLM-L6-v2
    -- Adjust if EMBEDDING_DIM env var changes.
    embedding        vector(384),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for fast cosine similarity search at scale
CREATE INDEX IF NOT EXISTS idx_docs_embedding_hnsw
    ON knowledge_docs USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_docs_source ON knowledge_docs (source);
