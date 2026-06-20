# TASK-033: Dedup, gate, cooldown, aggregation

**Status**: IN-PROGRESS · **Epic:** EPIC-08 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned**: Unassigned · **Started**: 2026-06-20 · **Analysis Completed**: 2026-06-20

## Description
Suppress alert fatigue: event-cluster dedup, threshold gating, cooldown on repeat conflicts, per-client aggregation into a needs-attention card.

## Acceptance Criteria
- [ ] no duplicate/daily-repeat alerts
- [ ] sub-threshold suppressed
- [ ] per-client rollup available

## Dependencies
TASK-032

## Refs
Requirements §15 AL5

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Models**: `Alert` (`backend/app/models/derived.py:173`) — `alert_class`, `status`, `evidence`, `confidence`, `client_id` already defined; composite index `ix_alerts_client_status_severity` already present
- **Dedup anchor**: `NewsItem.event_cluster_id` (`derived.py:104`) + `ix_news_event_cluster` index already in place — this is the event-cluster key §15 AL5 requires
- **Threshold constant**: `FIT_GAIN_THRESHOLD = 0.10` in `backend/app/loaders/swap.py:28` — E12 no-churn gate already defined, reuse without duplicating
- **Cooldown infrastructure**: `cache_set(key, value, ttl)` / `cache_get(key)` in `backend/app/redis_client.py:62–68` — TTL-keyed cooldown can be built entirely on top of these helpers; no new Redis helpers needed
- **Alert generation pattern**: `compute_drift()` in `backend/app/loaders/drift.py` — idempotent, per-client, `delete → recreate` pattern to extend
- **Enums**: `AlertStatus`, `Severity`, `ActionType` in `backend/app/models/enums.py` — full vocabulary already available
- **Admin router**: `backend/app/routers/admin.py` — `POST /admin/seed/drift` is the injection point for noise filter; `POST /admin/seed/alerts` will be TASK-032's endpoint
- **Read router**: `backend/app/routers/alerts.py` — `GET /clients/{id}/alerts` already exists; aggregation endpoint goes here

### Dependencies Required
- Backend packages: none new — `redis.asyncio`, `sqlalchemy`, `pydantic` all installed
- Database migrations: none required — noise filter is logic-only; cooldown lives in Redis; aggregation is read-side
- Docker services: Redis (already wired in `redis_client.py`), Postgres (already running)
- Blocker: TASK-032 must be started before news-impact and DNA-conflict alert dedup can be wired end-to-end; the noise module can be written and unit-tested independently first

### Impact Assessment

#### Files to Modify
- `backend/app/loaders/drift.py` — add `_noise_filter()` call before `session.add(Alert(...))` in both `_detect_drift_breaches` and `_detect_stale_sells`
- `backend/app/routers/alerts.py` — add `GET /clients/{id}/needs-attention` aggregation endpoint

#### Files to Create
- `backend/app/loaders/alert_noise.py` — the noise-control module (dedup, cooldown, gate, rollup)

#### Components Affected
- `drift.py` alert emission loop: MEDIUM — filter wraps existing `session.add()` calls; no logic change to detection
- `routers/alerts.py`: LOW — additive endpoint only; existing `/alerts` route unchanged
- `news_match.py` (TASK-032 territory): MEDIUM — TASK-032 must call the noise filter when producing news-impact alerts; coordinate interface now

#### API Changes
- New: `GET /clients/{client_id}/needs-attention` → `NeedsAttentionResponse` (severity counts + FYI rollup list)
- Existing `GET /clients/{client_id}/alerts` — no change

#### Database Changes
- None. Cooldown state is Redis-only (`cooldown:{client_id}:{alert_class}:{dedup_key}`, TTL 24 h). Dedup is a `SELECT EXISTS` query on `alerts` before insert.

### Implementation Blueprint

#### `backend/app/loaders/alert_noise.py`

```python
# Three independent functions; all pure or thin async wrappers.

COOLDOWN_TTL_S: int = 86_400          # 24-hour repeat suppression
FYI_ROLLUP_THRESHOLD: int = 3         # collapse ≥ N FYI alerts of same class → rollup card

async def should_suppress(
    session, redis, client_id, alert_class, dedup_key
) -> bool:
    """Returns True if this alert should be suppressed (dedup OR cooldown)."""
    # 1. DB dedup — same class + dedup_key already OPEN
    # 2. Redis cooldown — same class + dedup_key fired within 24h
    ...

async def record_cooldown(redis, client_id, alert_class, dedup_key) -> None:
    """Write a 24h Redis TTL key after an alert is emitted."""
    key = f"cooldown:{client_id}:{alert_class}:{dedup_key}"
    await cache_set(key, {"fired": True}, ttl=COOLDOWN_TTL_S)

def passes_threshold(value: float, threshold: float) -> bool:
    """Threshold gate — import FIT_GAIN_THRESHOLD from swap.py, don't duplicate."""
    return value > threshold

async def get_needs_attention(session, client_id) -> dict:
    """Aggregate open alerts into a per-client summary card."""
    # Count by severity; roll FYI alerts of same class into a single rollup entry
    ...
```

#### Dedup key convention
- drift_breach: `f"{sac}_{client_id}"` (sub-asset-class + client)
- stale_sell: `f"{isin}_{client_id}"`
- news_impact (TASK-032): `f"{event_cluster_id}_{client_id}"`
- dna_conflict (TASK-032): `f"{conflict_tag}_{client_id}"`

#### `GET /clients/{id}/needs-attention` response shape
```json
{
  "client_id": "...",
  "client_name": "...",
  "critical_count": 2,
  "attention_count": 5,
  "fyi_rollups": [
    {"alert_class": "news_impact", "count": 4, "sample_trigger": "..."}
  ],
  "total_open": 11
}
```

### Implementation Checklist
- [ ] Create `backend/app/loaders/alert_noise.py` with `should_suppress`, `record_cooldown`, `passes_threshold`, `get_needs_attention`
- [ ] Import and call `should_suppress` + `record_cooldown` in `drift.py` before `session.add(Alert(...))`
- [ ] Reuse `FIT_GAIN_THRESHOLD` from `swap.py` in `passes_threshold` (no duplication)
- [ ] Add `GET /clients/{id}/needs-attention` to `backend/app/routers/alerts.py`
- [ ] Register endpoint in `backend/app/main.py` (if not already via router include)
- [ ] Write unit tests for `should_suppress` and `passes_threshold` in `backend/tests/`
- [ ] Coordinate dedup_key convention with TASK-032 implementer
- [ ] Follow existing patterns: structlog `log.info(...)`, `session.commit()` per client, idempotent design

### Risk Analysis
- **Risk Level**: LOW
- **Main Risks**:
  - TASK-032 blocked: noise filter can still be coded and wired into `drift.py`; TASK-032 integration is additive. Mitigation: implement module now, add integration hook comment for TASK-032.
  - Redis unavailable: cooldown fails open (no suppression). Mitigation: wrap cooldown calls in `try/except`, log warning, allow alert through — safer than blocking on infrastructure fault.
  - Missing migration 0006: `0007_news_items_client_ids.py` references `down_revision = "0006"` but `0006` is absent from `migrations/versions/`. Unrelated to TASK-033 but worth noting — may cause `alembic upgrade head` to fail.

### Estimated Effort
- Original: S
- Adjusted: S
- Reason: All infrastructure (Redis, Alert model, event_cluster_id, FIT_GAIN_THRESHOLD) is already in place. This is purely logic wiring — one new module (~100 lines) + one new endpoint + drift.py integration.
