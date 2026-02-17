-- ============================================================
-- APPLICATION SCHEMA - metadata store, enrichment results, pgvector
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- Schema enrichment results
CREATE TABLE public.enriched_tables (
    id              SERIAL PRIMARY KEY,
    schema_name     VARCHAR(50)  NOT NULL,
    table_name      VARCHAR(100) NOT NULL,
    description     TEXT,                           -- LLM-generated description
    row_count       BIGINT,
    column_count    INTEGER,
    has_pk          BOOLEAN DEFAULT FALSE,
    enriched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    enrichment_model VARCHAR(50),                   -- which LLM generated this
    confidence      NUMERIC(3,2),                   -- 0.00-1.00
    UNIQUE(schema_name, table_name)
);

CREATE TABLE public.enriched_columns (
    id              SERIAL PRIMARY KEY,
    schema_name     VARCHAR(50)  NOT NULL,
    table_name      VARCHAR(100) NOT NULL,
    column_name     VARCHAR(100) NOT NULL,
    data_type       VARCHAR(50),
    is_nullable     BOOLEAN,
    description     TEXT,                           -- LLM-generated description
    sample_values   TEXT[],                         -- array of sample values
    distinct_count  BIGINT,
    null_pct        NUMERIC(5,2),
    enriched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(schema_name, table_name, column_name)
);

-- Inferred foreign keys
CREATE TABLE public.inferred_fks (
    id              SERIAL PRIMARY KEY,
    src_schema      VARCHAR(50)  NOT NULL,
    src_table       VARCHAR(100) NOT NULL,
    src_column      VARCHAR(100) NOT NULL,
    tgt_schema      VARCHAR(50)  NOT NULL,
    tgt_table       VARCHAR(100) NOT NULL,
    tgt_column      VARCHAR(100) NOT NULL,
    inference_method VARCHAR(30) NOT NULL,          -- 'name_match', 'inclusion_dep', 'llm_suggest'
    confidence      NUMERIC(3,2),
    validated       BOOLEAN DEFAULT FALSE,          -- expert-confirmed
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(src_schema, src_table, src_column, tgt_schema, tgt_table, tgt_column)
);

-- Query history and feedback loop
CREATE TABLE public.query_log (
    id              SERIAL PRIMARY KEY,
    question        TEXT NOT NULL,
    generated_sql   TEXT,
    executed_ok     BOOLEAN,
    execution_error TEXT,
    result_rows     INTEGER,
    feedback_score  INTEGER,                       -- 1-5 user rating, NULL if no feedback
    feedback_note   TEXT,
    corrected_sql   TEXT,                          -- expert correction (feeds back into RAG)
    llm_model       VARCHAR(50),
    latency_ms      INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Vector embeddings for RAG (using pgvector)
-- Stores embeddings for DDL, documentation, and SQL examples
CREATE TABLE public.rag_embeddings (
    id              SERIAL PRIMARY KEY,
    collection      VARCHAR(20) NOT NULL,          -- 'ddl', 'doc', 'sql_example'
    content         TEXT NOT NULL,                  -- the text that was embedded
    metadata        JSONB,                         -- extra info (table_name, difficulty, etc.)
    embedding       vector(768),                   -- all-mpnet-base-v2 = 768 dimensions
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for vector similarity search
CREATE INDEX idx_rag_embedding ON public.rag_embeddings
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- Evaluation benchmark pairs
CREATE TABLE public.benchmark (
    id              SERIAL PRIMARY KEY,
    question        TEXT NOT NULL,
    gold_sql        TEXT NOT NULL,
    difficulty      VARCHAR(15) NOT NULL,          -- easy/medium/hard/extra_hard
    category        VARCHAR(30),                   -- domain category
    tables_involved TEXT[],                        -- which tables the query touches
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);