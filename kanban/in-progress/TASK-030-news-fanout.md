# TASK-030: Inverted-index fan-out + LLM triage

**Status:** IN-PROGRESS · **Epic:** EPIC-07 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Match each polled article via inverted index (concept/theme to clients); cheap pre-filter, then LLM triage only on the shortlist for impact + draft. No LLM per article.

## Acceptance Criteria
- [ ] O(article) fan-out to clients
- [ ] LLM runs only on shortlist (F4)
- [ ] emits candidates to alert engine

## Dependencies
TASK-028 (IN-PROGRESS — `loaders/news_match.py` not yet landed; TASK-030 duplicates `_ImpactResult` schema until TASK-028 merges)
TASK-029 (IN-PROGRESS — `app/poller.py` not yet landed; it enqueues to `news:candidates` which TASK-030 consumes)
TASK-012 (**DONE** — `app/llm.py` fully implemented: `get_client()`, `chat()`, `json_chat()` with fence-strip + tenacity retries)

## Refs
Requirements §14.2 F3/F4

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`app/news.py`** — `NewsArticle` model (uri, title, body, url, source, published_at, sentiment). TASK-029's poller serialises these via `.model_dump()` into `news:candidates`. TASK-030 deserialises them with `NewsArticle.model_validate(payload)`.
- **`app/redis_client.py`** — `enqueue(queue, payload)` and `dequeue(queue, timeout)` FIFO queue helpers. Module docstring explicitly names TASK-029/030 as the intended consumers (line 7–9). No new imports needed.
- **`app/loaders/watchlist.py`** — `get_global_index(session)` and direct `select(ClientWatchlist)`. Each `ClientWatchlist` row has `entities: [{issuer, isin, valor, ticker}]`, `themes: [tag, ...]`, `keywords: [flat list]`. TASK-030 reads these to build the inverted index.
- **`app/llm.py`** — `json_chat(messages, schema)` with tenacity retries + fence-stripping. Same as used by `loaders/dna.py` and `loaders/style_profile.py`. Ready to consume.
- **`app/models/derived.py`** — `NewsItem` ORM (headline, source, url, published_at, sentiment, matched_holdings JSONB, matched_themes JSONB, impact Text, event_cluster_id Text + idx). TASK-030 upserts here after LLM triage — same upsert target as TASK-028.
- **`app/models/derived.py`** — `ClientWatchlist` ORM (client_id FK, entities JSONB, themes JSONB, keywords JSONB). The inverted index is derived entirely from these rows.
- **Migration 0001** — `news_items` table with all required columns. No new migration needed.
- **Migration 0005** — `client_watchlists` table. Depends on TASK-027 seed running first.
- **`loaders/dna.py`** — canonical per-client loop + `pg_insert().on_conflict_do_update()` + per-client commit pattern. TASK-030 follows this for NewsItem upserts.
- **TASK-029 queue name `news:candidates`** — per TASK-029 technical analysis; TASK-030 dequeues from here.

### Architecture: How TASK-030 fits

```
TASK-029 (poller)
  get_recent_activity(cursor, keywords=global_index)
  → enqueue("news:candidates", article.model_dump())

TASK-030 (fanout — this task)
  dequeue("news:candidates")
  → build_inverted_index(session)     # {keyword_lower: [client_id, ...]}
  → fanout_article(article, index)    # O(article) → {client_id: FanoutMatch}
  → triage_shortlist(matches)         # |sentiment|≥0.2 OR ≥2 hits
  → classify_shortlist(shortlist)     # LLM only on shortlist
  → upsert NewsItem rows
  → enqueue("news:alert_candidates", candidate_payload)  ← TASK-032 reads this

TASK-032 (alert engine — not yet started)
  dequeue("news:alert_candidates")
  → write Alert rows
```

### Inverted Index Design (§14.2 F3)

```python
# index: dict[str, list[str]]
# key   = keyword lowercased (issuer name, ticker, ISIN, or DNA theme tag)
# value = list of client_id strings whose watchlist contains this keyword
{
  "novartis": ["client-uuid-1", "client-uuid-3"],
  "pharma":   ["client-uuid-1", "client-uuid-2"],
  "nvs":      ["client-uuid-1"],
  "ch0012221716": ["client-uuid-1"],
  ...
}
```

**Build:** one pass over all `ClientWatchlist` rows — O(clients × keywords_per_client).
**Fan-out:** for each keyword in the index, check `keyword in (article.title + " " + article.body).lower()` — O(index_keywords × 1) per article. Multi-word phrases work with substring matching.
**Result per article:** `{client_id: {"keywords": [...], "own_hits": [...], "care_hits": [...]}}`

Entities (`entities[*].issuer`, `.ticker`, `.isin`) map to own-axis hits; `themes` map to care-axis hits. This preserves the §13.2 N2/N3 two-axis provenance that TASK-028 established.

### Shortlist Pre-filter (§14.2 F4)

A (client, article) pair is shortlisted when:
- `abs(article.sentiment or 0) >= 0.2` — non-neutral article
- OR `total_hits >= 2` — article strongly relevant (multiple watchlist terms matched)

Only shortlisted pairs receive an LLM call. Articles with only a single marginal keyword match and neutral sentiment are written to `news_items` with `impact = None` (no LLM cost, still retained for provenance).

### LLM Impact Schema

```python
class _ImpactResult(BaseModel):
    impact: Literal["threat", "opportunity", "non-financial moment"]
    reason: str          # explainability (R3 / G3)
    confidence: float    # [0,1]
```

Note: mirrors TASK-028's private `_ImpactResult`. Once TASK-028 lands, consolidate into a shared location (e.g. `app/models/derived.py` or `app/loaders/_news_shared.py`) and import from there. Until then TASK-030 defines it locally.

### Output Queue Payload — `news:alert_candidates`

```json
{
  "article_uri": "...",
  "client_id": "uuid-string",
  "matched_keywords": ["Novartis", "pharma"],
  "matched_holdings": [{"issuer": "Novartis", "valor": "1234", "axis": "own"}],
  "matched_themes":   [{"tag": "pharma", "axis": "care"}],
  "impact": "threat",
  "impact_reason": "Novartis defunding neuro research conflicts with client's pharma tilt.",
  "confidence": 0.87,
  "sentiment": -0.62,
  "news_item_id": "uuid-of-upserted-news-item"
}
```

TASK-032 reads this to create `Alert` rows with `alert_class = "news_impact"`.

### Dependencies Required
- Frontend packages: none
- Backend packages: none new — `httpx`, `sqlalchemy[asyncio]`, `openai`, `tenacity`, `redis` all in `requirements.txt`
- Database migrations: none — `news_items` (0001) and `client_watchlists` (0005) exist
- Docker services: none new — Redis and Postgres already running; Ollama/Phoeniqs via `llm.py`
- Seeding order: `seed/portfolio` → `seed/dna` → `seed/watchlist` (TASK-027) MUST precede fanout

### Impact Assessment

#### Files to Create
- `backend/app/loaders/news_fanout.py` — inverted index builder + fan-out + shortlist + LLM triage + NewsItem upsert + emit

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/fanout/news` (manual trigger for one fanout cycle; demo path) + update module docstring with TASK-030
- `backend/app/main.py` — wire a background consumer task that loops on `dequeue("news:candidates")` and calls `run_fanout()` (same pattern as TASK-029's poller task)

#### Components Affected
- `news_items` table: **HIGH** — TASK-030 is a second writer (alongside TASK-028); same upsert key (`event_cluster_id`)
- TASK-032 (alert engine): **HIGH dependency** — reads `news:alert_candidates` queue written here
- `backend/app/main.py`: **LOW** — one `asyncio.create_task` + cancel on shutdown
- `backend/app/routers/admin.py`: **LOW** — additive only

#### API Changes
- **New:** `POST /admin/fanout/news` → `{"status": "ok", "result": {"article": "uri", "matched_clients": N, "shortlisted": M, "emitted": K}}`

#### Database Changes
- `news_items` rows upserted (same schema as TASK-028; no conflict). `event_cluster_id = article.uri` as dedup key (§14.2 F5 — degrades gracefully to article-level dedup).

### Module Design (`backend/app/loaders/news_fanout.py`)

```python
# Public API (four functions):
#   build_inverted_index(session) → dict[str, list[str]]
#     SELECT all ClientWatchlist rows → map each keyword to client_ids.
#
#   fanout_article(article, index) → dict[str, FanoutMatch]
#     Scan article.title + body (lowercased) for each index keyword.
#     Return {client_id: FanoutMatch} for every client with ≥1 keyword hit.
#     O(index_keywords) per article — no per-client DB or API call.
#
#   classify_shortlist(session, article, shortlist) → dict[str, FanoutMatch]
#     Pre-filter: |sentiment|≥0.2 OR hits≥2.
#     LLM classify the pre-filtered pairs; update FanoutMatch.impact/reason/confidence.
#     Non-shortlisted pairs: impact = None.
#
#   run_fanout(session) → dict
#     1. dequeue("news:candidates", timeout=1)
#     2. If None → return {"article": None, "matched_clients": 0, ...}
#     3. build_inverted_index(session)  # rebuilt each call (acceptable at hackathon scale)
#     4. fanout_article(article, index) → matches
#     5. classify_shortlist(session, article, matches)
#     6. For each match: upsert NewsItem → enqueue("news:alert_candidates", payload)
#     7. Return stats dict

@dataclass
class FanoutMatch:
    client_id: str
    keywords:  list[str]     # all matched keywords
    own_hits:  list[dict]    # entity matches (own-axis)
    care_hits: list[dict]    # theme matches (care-axis)
    impact:    str | None    # set by LLM or None if not shortlisted
    reason:    str | None
    confidence: float | None
```

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Reuse `app/redis_client.py::enqueue()`/`dequeue()` — no direct Redis calls
- [ ] Reuse `app/llm.py::json_chat()` — no separate LLM client
- [ ] Reuse `ClientWatchlist` from `app/models/derived.py` — no duplicate model
- [ ] Reuse `pg_insert().on_conflict_do_update()` upsert pattern from `loaders/dna.py`
- [ ] Follow SOLID: `news_fanout.py` has no FastAPI imports; pure async service functions
- [ ] Upsert on `event_cluster_id = article.uri` — second fanout cycle doesn't duplicate rows
- [ ] Per-article commit (partial failure safety)
- [ ] `RuntimeError` if no `client_watchlists` rows (seeding order guard)
- [ ] LLM shortlist filter before calling `json_chat()` — cost control (§14.2 F4)
- [ ] Log `fanout.article_processed`, `fanout.cycle_complete` with structlog
- [ ] Idempotent: re-processing the same article uri upserts cleanly via `event_cluster_id`
- [ ] Add `POST /admin/fanout/news` to `admin.py`; update module docstring with TASK-030
- [ ] Wire background consumer into `main.py` lifespan (start after Redis up, cancel on shutdown)
- [ ] Define `_ImpactResult` locally; add a TODO comment to consolidate with TASK-028 on merge
- [ ] Maintain backwards compatibility — additive to existing tables; no schema change
- [ ] Write self-documenting code — function names describe their contract exactly

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - *TASK-028 `_ImpactResult` duplication:* MEDIUM — two private schemas that must stay in sync until consolidated. Mitigation: add a `# TODO: consolidate with TASK-028` comment; consolidate in one PR when TASK-028 merges.
  - *TASK-029 poller not yet started:* MEDIUM — `news:candidates` queue is empty until TASK-029 runs. Mitigation: `POST /admin/fanout/news` endpoint allows manual triggering; can also seed a test article directly via `enqueue("news:candidates", {...})` in tests.
  - *Inverted index rebuilt every cycle:* LOW — acceptable at 4–100 client scale. For 10k+ clients, cache in Redis or memory with TTL. Document as a known scaling limit.
  - *Multi-word keyword false positives:* LOW — "Novartis AG" substring matching is highly specific; ISINs and tickers even more so. Theme tags are single-word identifiers (per `loaders/watchlist.py::_build_themes`).
  - *LLM hallucinating impact outside Literal:* LOW — `json_chat()` retries with `tenacity`; `Literal` Pydantic validation rejects out-of-enum values and forces retry.
  - *Empty shortlist (all articles noise-level):* no LLM cost, correct behaviour — `run_fanout` returns `{"emitted": 0}` cleanly.

### Estimated Effort
- Original: M
- Adjusted: M (unchanged)
- Reason: Inverted index logic is straightforward (dict build + substring scan). The complexity is in correct wiring to TASK-028/029 and maintaining NewsItem upsert semantics. All plumbing (Redis queues, LLM client, DB models, upsert pattern) is done. Novel code: ~120 lines in `news_fanout.py` + admin endpoint + main.py wiring.
