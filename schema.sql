-- PostgreSQL + pgvector: knowledge base for RAG and persistent investigation state.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id        TEXT PRIMARY KEY,
  kind      TEXT NOT NULL CHECK (kind IN ('policy','exception','incident','architecture')),
  source    TEXT, version TEXT,
  status    TEXT NOT NULL CHECK (status IN ('active','deprecated','draft')),
  effective DATE, expires DATE,
  text      TEXT NOT NULL,
  metadata  JSONB DEFAULT '{}',
  embedding vector(256)            -- match config.EMBED_DIM / your embedding model
);
CREATE INDEX IF NOT EXISTS knowledge_embedding_idx ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS knowledge_kind_status_idx ON knowledge_chunks (kind, status);

CREATE TABLE IF NOT EXISTS investigations (
  id TEXT PRIMARY KEY, change_id TEXT, target TEXT, score INT, requires_human BOOLEAN,
  scoring_version TEXT, assessment JSONB, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS hypotheses (
  investigation_id TEXT REFERENCES investigations(id), id TEXT, parent TEXT, kind TEXT,
  statement TEXT, depth INT, score REAL, status TEXT, delta TEXT, evidence JSONB DEFAULT '[]',
  PRIMARY KEY (investigation_id, id));
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY, investigation_id TEXT, actor TEXT, event TEXT, detail JSONB, at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS engineer_feedback (
  id BIGSERIAL PRIMARY KEY, investigation_id TEXT, finding_id TEXT, confirmed BOOLEAN, confidence TEXT,
  reviewed BOOLEAN DEFAULT false, at TIMESTAMPTZ DEFAULT now());  -- reviewed rows feed controlled rule updates
