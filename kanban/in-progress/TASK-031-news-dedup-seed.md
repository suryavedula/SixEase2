# TASK-031: Event-cluster dedup and seeded triggers

**Status:** IN-PROGRESS · **Epic:** EPIC-07 · **Priority:** P1 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Dedup breaking stories via event clustering so one story surfaces once; seed/snapshot the four persona trigger articles so the demo is reliable offline.

## Acceptance Criteria
- [ ] duplicate sources collapse to one alert
- [ ] four seeded trigger articles available
- [ ] seeded data labelled (G6)

## Dependencies
TASK-030

## Refs
Requirements §14.4/§14.5 F5

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Model:** `backend/app/models/derived.py` — `NewsItem` already has `event_cluster_id: Mapped[str | None]` + `ix_news_event_cluster` index (designed for this dedup)
- **Migration:** `0001_initial_schema.py` — `news_items` table already created with `event_cluster_id` column and GIN indexes on `matched_holdings` / `matched_themes`
- **Pattern:** `backend/app/loaders/synthetic.py` — canonical model for seeded data: `[SYNTHETIC]` prefix (G6), idempotent, `random.Random(SEED=42)` for reproducibility; same pattern applies here
- **Admin router:** `backend/app/routers/admin.py` — established pattern: import loader → `@router.post("/seed/<name>")` → return `{"status": "ok", "loaded": counts}`
- **News client:** `backend/app/news.py` — `NewsArticle` Pydantic model; no dedup logic yet — that lives in the fan-out layer (TASK-030)
- **Watchlist:** `backend/app/loaders/watchlist.py` — `matched_themes` vocabulary: tags from DNA (e.g. `neuro-research`, `sustainability`, `fossil-fuel`, `luxury`, `us-tech`)

### Dependencies Required
- **Backend packages:** no new packages needed — SQLAlchemy, asyncpg already present
- **Database migrations:** new migration `0006` to add `is_seeded BOOLEAN NOT NULL DEFAULT FALSE` to `news_items` (G6 labelling)
- **Docker services:** PostgreSQL only (no LLM, no Event Registry call)
- **TASK-030 not required at runtime** — seed is standalone; dedup utility is written here and consumed by TASK-030 when it lands

### Impact Assessment

#### Files to Create / Modify
| File | Change |
|---|---|
| `backend/migrations/versions/0006_news_seeded.py` | New migration: add `is_seeded` column to `news_items` |
| `backend/app/models/derived.py` | Add `is_seeded: Mapped[bool]` to `NewsItem` |
| `backend/app/loaders/news_seed.py` | **New** — 4 trigger articles + `seed_news_triggers()` + `is_duplicate_cluster()` util |
| `backend/app/routers/admin.py` | Add `POST /admin/seed/news` endpoint + import |

#### Components Affected
| Component | Impact |
|---|---|
| `NewsItem` model | LOW — additive column only, no existing callers break |
| `admin.py` router | LOW — append-only, no existing endpoint changes |
| TASK-030 fan-out (future) | LOW — imports `is_duplicate_cluster()` from `news_seed.py` |
| TASK-032 alert engine | LOW — already reads `news_items`; `is_seeded` flag exposed for UI labelling |

#### API Changes
- **New:** `POST /admin/seed/news` → `{"status": "ok", "loaded": {"inserted": N, "skipped": N}}`
- No existing endpoints modified

#### Database Changes
- `news_items`: add `is_seeded BOOLEAN NOT NULL DEFAULT false` — non-destructive, existing rows default to `false`

### Four Scripted Trigger Articles (§D3)

One article per persona, one distinct use-case each:

| Persona | Use-case | Headline (scripted) | `impact` | `matched_themes` |
|---|---|---|---|---|
| Schneider | Behavioural guardrail | "AstraZeneca Shuts Down Neurological Disease Research Unit" | `threat` | `neuro-research`, `pharma` |
| Huber | Non-financial moment | "EU Sustainable Finance Package Passes — Green Bond Market to Double" | `moment` | `sustainability`, `fossil-fuel` |
| Räber | Swap trigger | "Intel Posts Fourth Consecutive Quarter of Revenue Decline" | `threat` | `us-tech` + `matched_holdings: Intel` |
| Ammann | Good-news moment | "LVMH and Richemont Report Record Q2 Sales as Asian Luxury Demand Rebounds" | `opportunity` | `luxury` |

Each gets a stable `event_cluster_id` (`seeded-cluster-<persona>-<topic>-2026`) and `is_seeded=True` (G6).

### Dedup Utility
`is_duplicate_cluster(existing_cluster_ids: set[str], cluster_id: str | None) -> bool`
- Pure function; no I/O — safe to unit-test
- Called by TASK-030's fan-out before writing each `NewsItem`
- Returns `False` for `None` cluster_id (ungrouped articles always pass through)

### Implementation Checklist
- [ ] Reuse `pg_insert` / idempotent upsert pattern from `synthetic.py` / `watchlist.py`
- [ ] Follow `[SEEDED]` source-name convention (analogue of `[SYNTHETIC]` prefix, G6)
- [ ] `is_seeded=True` on all four articles (G6 distinguishes seeded from live data)
- [ ] Migration is non-destructive (additive column, false default)
- [ ] Admin endpoint doc-string lists seeding order: `seed/portfolio → seed/dna → seed/news`
- [ ] `is_duplicate_cluster()` exported from loader for TASK-030 reuse

### Risk Analysis
- **Risk Level:** LOW
- **Risks:**
  - Persona-theme mapping wrong if CRM DNA extraction (TASK-016) produces different tag vocabulary → mitigation: use same tag strings as `synthetic.py` archetypes (`neuro-research`, `sustainability`, `luxury`, `us-tech`)
  - `event_cluster_id` uniqueness not DB-enforced (index is non-unique) → mitigation: application-level check in `seed_news_triggers`; TASK-030 will carry the same guard

### Estimated Effort
- Original: S
- Adjusted: S (confirmed — 4 files, no new packages, pure backend)
