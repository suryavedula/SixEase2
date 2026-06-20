# TASK-015: Embeddings and pgvector indexing

**Status**: IN-PROGRESS
**Assigned**: Unassigned
**Started**: 2026-06-20
**Analysis Completed**: 2026-06-20

**Epic:** EPIC-03 · **Priority:** P1 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20

## Description
Embed CRM notes and DNA attributes with a local embedding model; store vectors in pgvector for semantic retrieval and news-theme matching.

## Acceptance Criteria
- [ ] notes embedded and indexed
- [ ] similarity query endpoint
- [ ] used by DNA + news matching

## Dependencies
TASK-004, TASK-009, TASK-012

## Refs
Requirements §20 ST3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **Model:** `app/models/embedding.py` — `Embedding` table fully defined; polymorphic `(owner_type, owner_id)` design covers both `"interaction"` and `"client_dna"` owners. Docstring explicitly states "TASK-015 owns the actual embedding generation."
- **Migration:** `0001_initial_schema.py` — `embeddings` table + HNSW cosine index (`ix_embeddings_vector_hnsw`) already applied. **No new migration required.**
- **Config:** `app/config.py` already declares:
  - `embed_dim = 768` (matches `nomic-embed-text` output dimension)
  - `ollama_embed_model = "nomic-embed-text"`
  - `ollama_base_url = "http://ollama:11434/v1"`
- **LLM client:** `app/llm.py::get_client()` returns an `AsyncOpenAI` singleton. Ollama's `/v1/embeddings` endpoint is OpenAI-compatible, so `client.embeddings.create(model=settings.ollama_embed_model, input=[...])` works without a new client.
- **Data sources:**
  - `interactions.note` (Text) — the embedding input for CRM notes
  - `client_dna.*` (JSONB fields) — serialised into text for DNA embedding
- **Admin router:** `app/routers/admin.py` — pattern established for seed endpoints; TASK-015 adds `POST /admin/seed/embeddings` here.
- **Compose:** `ollama` service is active in `docker-compose.yml` with persisted volume `ollamadata`.

### Dependencies Required

- **Backend packages:** All already in `requirements.txt`:
  - `openai==1.54.0` — `AsyncOpenAI.embeddings.create()`
  - `pgvector==0.3.6` — `Vector` column type
  - `sqlalchemy[asyncio]==2.0.36` — async ORM session
- **Database migrations:** None — `embeddings` table + HNSW index exist in `0001`
- **Docker services:** `ollama` (active), `postgres` (active)
- **Ollama model pull required:** `ollama pull nomic-embed-text` must run before seeding; add a startup check or pre-pull in entrypoint

### Impact Assessment

#### Files to Create
- `backend/app/loaders/embeddings.py` — embedding generation + upsert logic (new module)
- `backend/app/routers/similarity.py` — similarity query router (new module)

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/seed/embeddings` endpoint
- `backend/app/main.py` — register `similarity` router

#### Components Affected
- `Embedding` model: LOW — already complete; used read-only
- `app/llm.py` `get_client()`: LOW — reused as-is; embeddings call via the same client object
- `app/config.py`: LOW — `ollama_embed_model` and `embed_dim` already wired; no changes needed
- `0001` migration: NONE — table + HNSW index already exist

#### API Changes
- `POST /admin/seed/embeddings` (NEW) — iterates all `Interaction` rows with non-null `note` and all `ClientDNA` rows; batch-embeds via Ollama; upserts into `embeddings` table
- `POST /similarity/search` (NEW) — accepts `{query: str, owner_type?: str, top_k?: int}`; embeds query, returns top-K results by cosine distance with owner metadata

#### Database Changes
- No schema changes. The `embeddings` table is already created by `0001_initial_schema.py`.
- The ANN query will use `SELECT ... ORDER BY vector <=> $1 LIMIT $k` (cosine distance operator from pgvector).

### Implementation Checklist

- [ ] Create `app/loaders/embeddings.py`:
  - `async def embed_texts(texts: list[str]) -> list[list[float]]` — calls `get_client().embeddings.create(model=settings.ollama_embed_model, input=texts)`; returns list of float vectors
  - `async def upsert_embedding(session, owner_type, owner_id, vector, model)` — SELECT existing then UPDATE, or INSERT new `Embedding` row (idempotent)
  - `async def seed_interaction_embeddings(session) -> int` — queries all `Interaction` rows where `note IS NOT NULL`, embeds notes in batches of 32, upserts
  - `async def seed_dna_embeddings(session) -> int` — queries all `ClientDNA` rows, serialises JSONB fields to a flat text representation, embeds, upserts
- [ ] Add `POST /admin/seed/embeddings` to `app/routers/admin.py` — calls both seed functions, returns counts
- [ ] Create `app/routers/similarity.py`:
  - `POST /similarity/search` — embed query text, run `SELECT id, owner_type, owner_id, vector <=> :qv AS distance FROM embeddings ORDER BY distance LIMIT :k`; return structured hits with owner_type/owner_id/distance
  - Support optional `owner_type` filter for targeted search (notes vs DNA)
- [ ] Register `similarity` router in `app/main.py`
- [ ] Reuse `get_client()` from `app/llm.py` — do NOT create a second Ollama client
- [ ] Batch embedding calls (32 texts/call) to avoid Ollama request-size issues
- [ ] Follow existing admin seed pattern: idempotent, structured log per batch, error → HTTPException
- [ ] Write self-documenting code consistent with existing module docstring style

### Risk Analysis

- **Risk Level:** LOW
- **Main Risks:**
  - `nomic-embed-text` not pulled in Ollama container: mitigation — add a try/except in `seed_interaction_embeddings` that surfaces a clear 500 with "model not found; run `ollama pull nomic-embed-text`"
  - `ClientDNA` table empty until TASK-016/017 run: mitigation — `seed_dna_embeddings` returns `{"client_dna": 0}` gracefully; similarity search over DNA still works once DNA rows exist
  - Dimension mismatch if a different embed model is used: mitigation — `embed_dim` in config is the single source of truth; changing the model requires a new migration to ALTER the column dimension (document in the module)

### Estimated Effort
- Original: S
- Adjusted: S
- Reason: Schema, config, client, and index are all pre-built by prior tasks. This task is purely the embedding generation logic (~120 LOC) and two endpoints.
