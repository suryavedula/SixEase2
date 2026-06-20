# TASK-027: Per-client watchlist builder

**Status:** IN-PROGRESS · **Epic:** EPIC-06 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Build watchlist = held entities (issuer/ticker/ISIN) UNION DNA themes per client; expose for news matching; maintain a global union index.

## Acceptance Criteria
- [ ] watchlist generated per client
- [ ] global union index for the poller
- [ ] themes sourced from DNA

## Dependencies
TASK-016 (**in-progress** — `loaders/dna.py` implemented; `client_dna` table has `exclusions`, `tilts`, `values` JSONB with `{text, tag, ...}` items)
TASK-026 (**in-progress** — `loaders/holdings.py` implemented; `positions` table has `issuer`, `isin`, `valor`, `yahoo` columns)

## Refs
Requirements §13 (watchlist), §14.2 F1

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`positions` table** (`backend/app/models/source.py:54`) — `issuer`, `isin`, `valor`, `mic`, `yahoo` (ticker) columns per holding. Indexed on `valor` and `isin`. These are the "own-axis" entity identifiers for news matching.
- **`ClientDNA` ORM model** (`backend/app/models/derived.py:43`) — `exclusions`, `tilts`, `values` JSONB columns. Each item: `{text, tag, source_note_ids, confidence}`. The `tag` field (e.g. `"pharma"`, `"neuro-research"`) is the "care-axis" DNA theme keyword.
- **`VALID_TAGS`** (`backend/app/loaders/dna.py:28`) — canonical tag vocabulary; watchlist themes are drawn from this set.
- **`news.py`** (`backend/app/news.py`) — `search_articles(keywords, concepts)` and `get_recent_activity(newest_uri, keywords, concepts)` — the keywords/concepts params accept exactly the flat string lists the watchlist produces.
- **`NewsItem` model** (`backend/app/models/derived.py:92`) — `matched_holdings` / `matched_themes` JSONB + GIN indexes already built in migration 0001. The watchlist's entity and theme lists are what TASK-028 (news matching) uses to populate these fields.
- **Loader pattern** (`backend/app/loaders/dna.py`, `backend/app/loaders/holdings.py`) — async, idempotent upsert with per-client commit; returns `dict[str, int]` counts. Follow exactly.
- **Admin router pattern** (`backend/app/routers/admin.py:20`) — `POST /admin/seed/*`; module docstring lists tasks. TASK-027 adds one entry.
- **`portfolio.py` router** (`backend/app/routers/portfolio.py:23`) — established read-endpoint pattern for `/clients/{id}/...`. New `/clients/{id}/watchlist` fits naturally here.

### Schema Gap

No `client_watchlists` table exists in any migration. **A new migration 0005 is required.**

### Data Flow

```
positions (issuer, isin, valor, yahoo)  ──────────────┐
                                                       ▼
client_dna (exclusions.tag, tilts.tag, values.tag) ──► build_watchlists()
                                                       │
                                          ┌────────────┴────────────┐
                                          ▼                         ▼
                               client_watchlists             (global index)
                              (one row per client)       computed from all rows
                                entities: [{issuer,        keywords: distinct
                                  isin, valor, ticker}]    union of all
                                themes: ["pharma", ...]    client keywords
                                keywords: flat union list
                                          │
                                          ▼
                              news.search_articles(keywords=...)  ← TASK-028
                              news.get_recent_activity(keywords=...)  ← TASK-029
```

### `client_watchlists` Table Design

```sql
CREATE TABLE client_watchlists (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   UUID NOT NULL UNIQUE REFERENCES clients(id) ON DELETE CASCADE,
    entities    JSONB,   -- [{issuer, isin, valor, ticker}] deduplicated by ISIN
    themes      JSONB,   -- [tag_string, ...] from DNA exclusions + tilts + values
    keywords    JSONB,   -- flat list: issuer names + tickers + ISINs + theme tags
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Why `keywords` is a denormalised flat list:** `news.search_articles()` and `get_recent_activity()` take `keywords: list[str]`. Pre-flattening avoids recomputation on every poll cycle.

**Entity deduplication rule:** group by `isin` (preferred), falling back to `issuer` if ISIN is null. This collapses multiple positions in the same company into one entity.

**Theme extraction:** collect the `tag` field from every item in `client_dna.exclusions`, `client_dna.tilts`, and `client_dna.values`; drop `None` tags; deduplicate.

### Global Index

`get_global_index(session)` queries all `client_watchlists` rows and returns the deduplicated union of `keywords` across all clients. No separate table needed — the global union is a O(N clients) aggregation query, called once per poll cycle by TASK-029. This is consistent with §14.2 F1: "distinct set grows sublinearly."

### Dependencies Required

- **Backend packages:** none new — SQLAlchemy, asyncpg already in `requirements.txt`
- **Database migrations:** new `0005_client_watchlists.py` (one new table, one index)
- **Seeding order:** `seed/dna` must run before `seed/watchlist` (DNA themes must exist); `seed/portfolio` must run before `seed/watchlist` (positions must exist)

### Impact Assessment

#### Files to Create
- `backend/migrations/versions/0005_client_watchlists.py` — add `client_watchlists` table
- `backend/app/loaders/watchlist.py` — `build_watchlists(session, client_id=None) → dict[str, int]` + `get_global_index(session) → dict`

#### Files to Modify
- `backend/app/models/derived.py` — add `ClientWatchlist` ORM model
- `backend/app/routers/admin.py` — add `POST /admin/seed/watchlist` + update module docstring
- `backend/app/routers/portfolio.py` — add `GET /clients/{client_id}/watchlist` and `GET /watchlist/global` (or a new thin router)

#### Components Affected
- `client_watchlists` table: **HIGH** (first write — TASK-027 creates all client rows)
- TASK-028 (news matching): **HIGH dependency** — reads per-client `keywords` to issue entity + thematic queries
- TASK-029 (news poller): **HIGH dependency** — calls `get_global_index()` to build the single poll filter (§14.2 F1/F2)
- TASK-016 (DNA): **LOW** — TASK-027 reads DNA; does not modify it

#### API Changes
- **New:** `POST /admin/seed/watchlist` → `{"status": "ok", "loaded": {"Eugen Räber": 1, ...}}`
- **New:** `GET /clients/{client_id}/watchlist` → `{client_id, client_name, entities: [...], themes: [...], keywords: [...]}`
- **New:** `GET /watchlist/global` → `{client_count: 4, keyword_count: N, keywords: [...]}`

#### Database Changes
- New table `client_watchlists` via migration 0005. No changes to existing tables.

### Module Design (`backend/app/loaders/watchlist.py`)

```python
# Public API:
#   build_watchlists(session, client_id=None) → dict[str, int]
#     Upsert one ClientWatchlist row per client.
#     Returns {client_name: 1} for each processed client.
#
#   get_global_index(session) → dict
#     Returns {"keywords": [...], "client_count": N, "keyword_count": N}
#     The global union used by TASK-029's poller.

async def build_watchlists(session, client_id=None) -> dict[str, int]:
    # 1. SELECT clients (all or one)
    # 2. Per client:
    #    a. SELECT DISTINCT issuer/isin/valor/yahoo FROM positions WHERE client_id = X
    #       → deduplicate by isin (or issuer if isin is null)
    #       → entities list + contribution to keywords
    #    b. SELECT exclusions, tilts, values FROM client_dna WHERE client_id = X
    #       → collect non-None tag fields → themes list
    #       → raise RuntimeError if no DNA row (seeding order violation)
    #    c. keywords = [e["issuer"] for e in entities if e["issuer"]]
    #                + [e["ticker"] for e in entities if e["ticker"]]
    #                + [e["isin"] for e in entities if e["isin"]]
    #                + themes
    #       → deduplicate, drop empty strings
    #    d. Upsert ClientWatchlist via pg_insert(...).on_conflict_do_update(index_elements=["client_id"])
    #    e. Commit per client

async def get_global_index(session) -> dict:
    # SELECT keywords FROM client_watchlists
    # Flatten and deduplicate all keyword lists
    # Return {keywords: [...], client_count: N, keyword_count: N}
```

### Implementation Checklist
- [ ] Write `backend/migrations/versions/0005_client_watchlists.py` — CREATE TABLE + index on `client_id`
- [ ] Add `ClientWatchlist` model to `backend/app/models/derived.py` (unique FK on `client_id`, JSONB `entities`/`themes`/`keywords`)
- [ ] Write `backend/app/loaders/watchlist.py` with `build_watchlists()` and `get_global_index()`
- [ ] Entity deduplication: group positions by ISIN; fallback-group by issuer for null-ISIN rows
- [ ] Theme extraction: collect `.tag` from `exclusions` + `tilts` + `values`; drop `None`; deduplicate
- [ ] Keywords: flat union of issuer names, tickers, ISINs, + theme tags; deduplicate; drop empty strings
- [ ] `RuntimeError` if no `client_dna` row found for a client (seeding order guard)
- [ ] Upsert `ClientWatchlist` with `on_conflict_do_update(index_elements=["client_id"])`
- [ ] Per-client commit (partial failure safety — same as `dna.py` and `holdings.py`)
- [ ] Add `POST /admin/seed/watchlist` to `admin.py`; update module docstring with TASK-027
- [ ] Add `GET /clients/{id}/watchlist` to `portfolio.py`
- [ ] Add `GET /watchlist/global` (can be in `portfolio.py` with prefix override, or a new `news.py` router)
- [ ] Log `watchlist.client_built` and `watchlist.build_complete` with structlog
- [ ] Reuse `pg_insert` / `on_conflict_do_update` pattern from `dna.py`; no new import needed
- [ ] Follow SOLID: `watchlist.py` has no FastAPI imports; pure async service function
- [ ] Idempotent: second `seed/watchlist` call overwrites existing rows cleanly

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *DNA not yet seeded when `seed/watchlist` is called* — mitigation: `RuntimeError` with clear message, same guard pattern as `dna.py` and `holdings.py`.
  - *NULL issuer/isin/ticker on some positions* — mitigation: guard `if x:` before adding to keywords list; some positions (e.g., bonds) may lack a Yahoo ticker.
  - *DNA `values` items have no `tag`* — mitigation: only include items where `item.get("tag")` is truthy; the `text` field is too long for news search terms.
  - *Duplicate keyword strings across axes* — mitigation: deduplicate the flat `keywords` list with `list(dict.fromkeys(...))` to preserve order while removing duplicates.
  - *`client_dna.exclusions` / `tilts` / `values` are null if DNA not yet extracted* — mitigation: same RuntimeError guard; seeding doc says `seed/dna → seed/watchlist`.

### Estimated Effort
- Original: **S**
- Adjusted: **S** — both dependency tables are available; loader + migration + two endpoints; no LLM calls; pure data assembly. The main work is the entity deduplication logic and wiring up the global index. ~1–2 hours.
