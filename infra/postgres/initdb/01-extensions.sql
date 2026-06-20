-- TASK-001: enable pgvector on first boot.
-- The pgvector/pgvector image ships the extension; this just activates it in the default DB.
-- (Schema, tables, and Alembic migrations are owned by TASK-004 — nothing else belongs here.)
CREATE EXTENSION IF NOT EXISTS vector;
