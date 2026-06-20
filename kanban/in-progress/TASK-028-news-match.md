# TASK-028: News matching and impact classification

**Status:** IN-PROGRESS · **Epic:** EPIC-06 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20 · **Implemented:** 2026-06-20

## Description
Match articles to clients on own-axis (entity) and care-axis (theme); score relevance + sentiment; classify impact as threat/opportunity/non-financial moment; keep provenance.

## Acceptance Criteria
- [x] articles linked to holdings/themes with scores
- [x] impact classified (R2)
- [x] provenance retained for alerts (N5/R3)

## Dependencies
TASK-014 (**DONE** — `backend/app/news.py` fully implemented: `search_articles()`, `get_recent_activity()`, `NewsArticle` model)
TASK-027 (**IN-PROGRESS** — `client_watchlists` table + `build_watchlists()` + `get_global_index()` not yet landed; **HARD BLOCKER** — TASK-028 reads `client_watchlists.entities`, `.themes`, `.keywords`)

## Refs
Requirements §13.2/§13.3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`news_items` table** (migration `0001_initial_schema.py:206`) — ALL required columns already exist: `headline`, `source`, `url`, `published_at`, `sentiment` (Float), `matched_holdings` (JSONB + GIN), `matched_themes` (JSONB + GIN), `impact` (Text), `event_cluster_id` (Text + idx). **No new migration needed.**
- **`NewsItem` ORM model** (`backend/app/models/derived.py:92`) — ready to upsert into; `matched_holdings` = own-axis hits; `matched_themes` = care-axis hits; `impact` = threat/opportunity/non-financial moment.
- **`backend/app/news.py`** — complete Event Registry client (TASK-014). `search_articles(keywords, concepts)` takes exactly the flat keyword list that `client_watchlists.keywords` produces. `NewsArticle` model has `uri`, `title`, `body`, `source`, `published_at`, `sentiment`.
- **`client_watchlists` table** (TASK-027 migration 0005, in-progress) — will provide per-client `entities: [{issuer, isin, valor, ticker}]`, `themes: [tag, ...]`, `keywords: [flat list]`. `get_global_index(session)` returns the cross-client union for the §14.2 F3 local fan-out.
- **`app/llm.py::json_chat()`** — structured LLM call for impact classification (R2). Pattern already established in `loaders/dna.py` and `loaders/style_profile.py`.
- **`Citation` model** (`backend/app/models/citation.py:22`) — polymorphic evidence table; `SourceType.NEWS` enum value exists. `NewsItem` rows ARE the citeable source — downstream alert tasks (TASK-032) write `Citation(owner_type="alert", source_type=NEWS, source_id=news_item.id)`; TASK-028 does NOT write citations.
- **`loaders/dna.py`** — canonical pattern: per-client `select`, per-client LLM call, per-client commit, `RuntimeError` guard for missing prerequisites.
- **Admin router** (`backend/app/routers/admin.py`) — additive endpoint pattern; module docstring listing; `log.error` + `HTTPException` wrapping.

### Two-Axis Matching Design (§13.2 N2–N3, §13.3 R1)

```
client_watchlists.entities  →  own-axis matching  →  matched_holdings
client_watchlists.themes    →  care-axis matching →  matched_themes
```

**Own-axis (entities):** For each `NewsArticle`, scan `headline + body` (lowercased) for the client's entity identifiers — `issuer`, `ticker` (`yahoo`), and `isin`. Collect all matching entity dicts into `matched_holdings`. Each entry: `{issuer, valor, isin, ticker, axis: "own"}`.

**Care-axis (themes):** Scan the same text for each `theme` string from `client_watchlists.themes`. Collect matching theme strings into `matched_themes`. Each entry: `{tag, axis: "care"}`.

**Filter:** Only articles with ≥1 hit (own OR care axis) are persisted as `NewsItem` rows. Articles with zero matches are discarded (N4: "only watchlist-relevant items are retained").

**Relevance score:** `own_hits * 2 + care_hits` (own-axis weighted 2× per §13.3 R1 — entity match is stronger signal). Stored in `matched_holdings`/`matched_themes` list lengths; not a separate column (no migration).

**Event dedup (§14.2 F5):** Use `news_item.uri` as the dedup key (stored in `event_cluster_id`). Upsert via `ON CONFLICT DO UPDATE` on `event_cluster_id`. If Event Registry returns `eventUri` in future (requires `NewsArticle` model extension), swap to that for story-level dedup.

### Impact Classification (§13.3 R2, §14.2 F4)

LLM runs only on the **shortlist**: articles with `|sentiment| ≥ 0.2` OR `≥2 total hits`. Avoids calling the LLM on every marginally-relevant article.

```python
class _ImpactResult(BaseModel):
    impact: Literal["threat", "opportunity", "non-financial moment"]
    reason: str          # explainability per R3 / G3
    confidence: float    # [0,1]
```

Prompt: headline + body (first 500 chars) + which issuer/theme matched + client mandate → one of three labels. Result stored in `news_items.impact`. Articles below the shortlist threshold get `impact = None`.

### Provenance (§13.2 N5, §13.3 R3)

- The `NewsItem` row itself IS the provenance: `source`, `url`, `published_at` satisfy N5.
- `matched_holdings` and `matched_themes` satisfy R3 ("states which holding or theme matched and why").
- Downstream TASK-032 (alerts) writes `Citation(owner_type="alert", source_type=NEWS, source_id=news_item.id)` to link alerts back to the article. TASK-028 does NOT write Citation rows.

### Dependencies Required

- **Backend packages:** none new — `httpx`, `sqlalchemy[asyncio]`, `openai` (for `json_chat`), `tenacity` all already in `requirements.txt`
- **Database migrations:** none — `news_items` table exists from migration 0001
- **Docker services:** none new — Ollama/Phoeniqs (LLM) already wired via `app/llm.py`
- **Seeding order:** `seed/watchlist` (TASK-027) MUST run before `scan/news` (TASK-028)

### Impact Assessment

#### Files to Create
- `backend/app/loaders/news_match.py` — two-axis matching + LLM classification + `NewsItem` upserts

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/scan/news` + update module docstring
- `backend/app/news.py` — LOW: optionally add `event_uri: str | None` to `NewsArticle` for story-level dedup; backward-compatible `_parse_articles` `.get("eventUri")` addition

#### Components Affected
- `news_items` table: **HIGH** — TASK-028 is the sole writer; all matched article rows land here
- TASK-032 (alerts from news): **HIGH dependency** — reads `news_items` rows written here, writes Citations back to them
- TASK-029 (news poller): **MEDIUM** — poller feeds articles into TASK-028's `match_articles()` on each poll cycle
- `backend/app/news.py`: **LOW** — additive only (`event_uri` field is optional)
- `backend/app/routers/admin.py`: **LOW** — additive only

#### API Changes
- **New:** `POST /admin/scan/news` → `{"status": "ok", "loaded": {"Eugen Räber": 3, "Petra Schneider": 1, ...}}`

#### Database Changes
- `news_items` rows inserted (none exist yet). No schema change.

### Module Design (`backend/app/loaders/news_match.py`)

```python
# Public API:
#   match_articles(session, client_id, watchlist, articles) → dict[str, int]
#     Match pre-fetched articles against the client's watchlist; upsert NewsItem rows.
#     Returns {"matched": N, "classified": M} for the client.
#
#   scan_news_for_client(session, client_id) → dict[str, int]
#     Load client's watchlist → fetch articles via search_articles() → call match_articles().
#
#   scan_news_all_clients(session) → dict[str, int]
#     Iterate all clients; return {client_name: matched_count, ...}.

async def match_articles(session, client_id, watchlist, articles):
    # 1. For each article:
    #    a. own-axis: scan title+body for entity identifiers → matched_holdings list
    #    b. care-axis: scan title+body for theme keywords → matched_themes list
    #    c. If total hits == 0: skip (discard)
    # 2. Shortlist: |sentiment| >= 0.2 OR total_hits >= 2
    # 3. LLM classify shortlisted articles → news_item.impact
    # 4. Upsert NewsItem via pg_insert().on_conflict_do_update(index_elements=["event_cluster_id"])
    # 5. Per-client commit
    # 6. Return {"matched": len(persisted), "classified": len(shortlisted)}

async def scan_news_for_client(session, client_id):
    # 1. SELECT ClientWatchlist WHERE client_id = ? → raise RuntimeError if missing
    # 2. search_articles(keywords=watchlist.keywords, count=50)
    # 3. return await match_articles(session, client_id, watchlist, articles)

async def scan_news_all_clients(session):
    # SELECT clients → per-client scan_news_for_client(); accumulate counts
```

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Reuse `app/news.py::search_articles()` — no duplicate HTTP calls
- [ ] Reuse `app/llm.py::json_chat()` — no separate LLM client
- [ ] Reuse `client_watchlists` (TASK-027) — no re-reading `positions`/`client_dna` directly
- [ ] Reuse `pg_insert().on_conflict_do_update()` pattern from `dna.py` and `watchlist.py`
- [ ] Follow SOLID: `news_match.py` has no FastAPI imports; pure async service functions
- [ ] Upsert on `event_cluster_id` (dedup key): second scan does not duplicate rows
- [ ] Per-client commit (partial failure safety — same as `dna.py`, `watchlist.py`)
- [ ] `RuntimeError` if no `client_watchlists` row for client (seeding order guard)
- [ ] LLM shortlist filter before calling `json_chat()` — cost control (§14.2 F4)
- [ ] Log `news_match.client_scanned`, `news_match.scan_complete` with structlog
- [ ] Idempotent: second `scan/news` call upserts existing rows cleanly
- [ ] Add proper error handling — `raise_for_status()` already in `news.py`; catch LLM parse failures with `tenacity` / graceful fallback to `impact=None`
- [ ] Include `event_uri` extraction from raw payload if present (backward-compatible `news.py` extension)
- [ ] Add `POST /admin/scan/news` to `admin.py`; update module docstring with TASK-028
- [ ] Follow CLAUDE.md: NEVER create duplicate match or LLM components

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - *TASK-027 not complete:* HARD BLOCKER — cannot read `client_watchlists`. **Mitigation:** start only after TASK-027 merges, or implement a fallback that reads positions + client_dna directly (duplicates TASK-027 logic — avoid).
  - *LLM hallucinating impact labels:* mitigated — structured JSON output with `Literal["threat", "opportunity", "non-financial moment"]`; `json_chat()` retries via tenacity; if parse fails, `impact = None` (non-fatal).
  - *Event Registry sentiment absent on some articles:* mitigated — `NewsArticle.sentiment` is already `float | None`; shortlist filter handles `None` with `abs(s or 0)`.
  - *`event_cluster_id` not returned by API:* mitigated — fall back to article `uri` as the dedup key; story-level dedup (§14.2 F5) degrades to article-level dedup, which is still correct.
  - *High article volume → slow LLM calls:* mitigated — shortlist filter (|sentiment| ≥ 0.2 OR ≥2 hits) limits LLM invocations to the most relevant subset; `count=50` in `search_articles()` caps fetch size.
  - *Keyword false positives (e.g. common words):* mitigated — entity matching uses full issuer names, not abbreviations; ISIN/ticker matching is highly specific.

### Estimated Effort
- Original: M
- Adjusted: M (unchanged)
- Reason: All plumbing exists (news client, LLM, DB schema, loader pattern). The novel logic is the two-axis keyword scan and the LLM shortlisting — well-scoped, no unknowns. TASK-027 dependency is the only risk to the schedule.
