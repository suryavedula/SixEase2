# TASK-034: Prioritisation, severity, action-type

**Status:** IN-PROGRESS · **Epic:** EPIC-08 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Rank alerts by impact x relevance x urgency x emotional-weight (not AUM); assign severity (Critical/Attention/FYI) and action type (Trade/Reach-out/Inform/Watch).

## Acceptance Criteria
- [ ] ranking favours emotional weight over AUM (AL6)
- [ ] severity + action type set (AL2/AL4)
- [ ] one event can yield trade + reach-out

## Dependencies
TASK-032 (**IN-PROGRESS** — `loaders/alerts.py` fully implemented; all 8 non-drift alert classes generated with `severity` + `action_type` already set at generation time; `POST /admin/seed/alerts` wired in `admin.py`)

## Refs
Requirements §15 AL2/AL4/AL6

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`backend/app/models/derived.py:173` `Alert`** — already has `severity` (SAEnum), `action_type` (SAEnum), `confidence` (Float), `status`, `evidence` (JSONB). No `rank_score` column yet — **migration needed**.
- **`backend/app/models/enums.py`** — `ActionType.{TRADE, REACH_OUT, ACKNOWLEDGE, WATCH}`, `Severity.{CRITICAL, ATTENTION, FYI}` — all action/severity values already present; no new enum members needed.
- **`backend/app/models/derived.py:43` `ClientDNA.temperament`** — `Text` column holding extracted client temperament (e.g. "high-anxiety", "analytical"). Source for `emotional_weight` factor.
- **`backend/app/routers/alerts.py:71`** — current sort is `_SEVERITY_ORDER` (CRITICAL=0, ATTENTION=1, FYI=2) + recency tiebreaker. Replace with `rank_score DESC` once the column exists.
- **`backend/app/loaders/alerts.py`** — `_generate_news_alerts` currently picks **one** `action_type` per event (TRADE if own-axis, else REACH_OUT). Needs a change to emit **two** `Alert` rows when both `has_own_axis` and `has_care_axis` are true — one TRADE + one REACH_OUT — to satisfy "one event can yield trade + reach-out".
- **`backend/app/loaders/drift.py`** — canonical idempotency pattern (DELETE per client → re-insert → commit). Reuse pattern exactly in `alert_rank.py`.
- **`backend/app/logging.py`** — `get_logger(__name__)` already the project standard.
- **`backend/app/routers/admin.py`** — `POST /admin/seed/alerts` registered; add `POST /admin/seed/rank` following the same pattern.
- **Migrations `0001–0007`** — next revision is **`0008`**. Pattern: `op.add_column` with `sa.Column("rank_score", sa.Float(), nullable=True)`.

### Dependencies Required
- Frontend packages: none (backend-only)
- Backend packages: none new — `sqlalchemy[asyncio]`, `asyncpg` already present
- Database migrations: **`0008_alert_rank_score.py`** — adds `rank_score Float` column to `alerts` table
- Docker services: postgres (already running); no Ollama/Redis needed for ranking
- Seeding order: `seed/alerts` + `seed/drift` → **`seed/rank`** (rank runs over existing alerts)

### Impact Assessment

#### Files to Create
- `backend/app/loaders/alert_rank.py` — `compute_rank_score(alert, temperament) -> float` + `rank_alerts(session, client_id=None) -> dict`
- `backend/migrations/versions/0008_alert_rank_score.py` — adds `rank_score Float` column

#### Files to Modify
- `backend/app/models/derived.py` — add `rank_score: Mapped[float | None] = mapped_column(Float)` to `Alert`
- `backend/app/loaders/alerts.py` — modify `_generate_news_alerts` to emit a second alert (REACH_OUT) when `has_own_axis AND has_care_axis`, in addition to the TRADE alert
- `backend/app/routers/alerts.py` — replace Python sort key with `rank_score DESC` (nulls last)
- `backend/app/routers/admin.py` — add `POST /admin/seed/rank` + update docstring

#### Components Affected
- `alerts` table: **HIGH** — new `rank_score` column; values written by `seed/rank`
- `routers/alerts.py` GET response: **LOW** — ordering change only; response shape unchanged
- `loaders/alerts.py` news generator: **LOW** — additive (new row when both axes match); existing dedup still applies per cluster per class
- `admin.py`: **LOW** — additive endpoint only

#### API Changes
- New: `POST /admin/seed/rank` → `{"status":"ok","loaded":{"clients_processed":N,"alerts_ranked":N}}`
- Modified ordering: `GET /clients/{id}/alerts` now returns alerts sorted by `rank_score DESC` instead of severity tier

#### Database Changes
- `alerts` table: add `rank_score Float NULL` (migration 0008)

---

### Ranking Formula

```python
# loaders/alert_rank.py

_SEVERITY_BASE = {
    "CRITICAL": 3.0,
    "ATTENTION": 2.0,
    "FYI": 1.0,
}

_CLASS_WEIGHT = {
    "dna_conflict":          1.00,  # forced exclusion breach — hardest constraint
    "panic":                 0.95,  # client emotional risk on held position
    "quiet_client":          0.90,  # relationship health decay
    "drift_breach":          0.85,  # mandate integrity
    "news_impact":           0.80,  # live market signal
    "overdue_promise":       0.75,  # explicit client commitment
    "stale_sell":            0.70,  # portfolio hygiene
    "behavioural_guardrail": 0.60,  # pre-emptive check
    "values_drift":          0.50,  # soft portfolio-level signal
    "good_news":             0.40,  # relationship moment (lowest urgency)
}

_EMOTIONAL_KEYWORDS = frozenset({
    "anxious", "anxiety", "worried", "reactive", "emotional",
    "nervous", "impulsive", "fearful", "panic",
})

def _emotional_multiplier(temperament: str | None, alert: Alert) -> float:
    """Boost REACH_OUT + panic alerts for emotionally reactive clients."""
    if not temperament:
        return 1.0
    t_lower = temperament.lower()
    is_reactive = any(kw in t_lower for kw in _EMOTIONAL_KEYWORDS)
    if is_reactive and (
        alert.action_type.value == "REACH_OUT"
        or alert.alert_class in ("panic", "quiet_client", "good_news")
    ):
        return 1.3
    return 1.0

def compute_rank_score(alert: Alert, temperament: str | None) -> float:
    """
    rank = severity_base × class_weight × confidence × emotional_multiplier
    All factors are ≥0; CRITICAL dna_conflict with high confidence ranks highest.
    Not AUM-based (AL6 / UC-24).
    """
    sev = alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity)
    severity_base  = _SEVERITY_BASE.get(sev, 1.0)
    class_weight   = _CLASS_WEIGHT.get(alert.alert_class or "", 0.5)
    confidence     = alert.confidence if alert.confidence is not None else 0.5
    emo_mult       = _emotional_multiplier(temperament, alert)
    return severity_base * class_weight * confidence * emo_mult
```

### Multi-action-type (TRADE + REACH_OUT from one event)

Modify `_generate_news_alerts` in `loaders/alerts.py`:

```python
# When a threat/opportunity news item hits a held position (own-axis) AND a care theme (care-axis)
# emit TWO alerts: one TRADE, one REACH_OUT. Separate dedup keys to allow both through.
if impact == "threat" and has_own_axis and cluster not in seen["news_impact_trade"]:
    seen["news_impact_trade"].add(cluster)
    session.add(Alert(..., action_type=ActionType.TRADE, ...))
    count += 1
if impact == "threat" and has_care_axis and cluster not in seen["news_impact_reach"]:
    seen["news_impact_reach"].add(cluster)
    session.add(Alert(..., action_type=ActionType.REACH_OUT, alert_class="news_impact", ...))
    count += 1
```

The two alerts share `alert_class="news_impact"` but differ in `action_type`. Noise control (TASK-033) deduplication uses `event_cluster_id`, but since action_type differs, both survive the TASK-033 filter (dedup is per class+cluster, not per class+cluster+action_type).

### Implementation Checklist
- [ ] Create `backend/migrations/versions/0008_alert_rank_score.py` — `op.add_column("alerts", sa.Column("rank_score", sa.Float(), nullable=True))`
- [ ] Add `rank_score: Mapped[float | None] = mapped_column(Float)` to `Alert` in `models/derived.py`
- [ ] Create `backend/app/loaders/alert_rank.py` with `compute_rank_score(alert, temperament) -> float` and `rank_alerts(session, client_id=None) -> dict`
- [ ] `rank_alerts`: load all clients (or one), get their DNA temperament, compute+write `rank_score` for each open alert; commit per client
- [ ] Modify `_generate_news_alerts` in `loaders/alerts.py` to emit TRADE + REACH_OUT pair when `has_own_axis AND has_care_axis`; use separate seen-sets `seen["news_impact_trade"]` and `seen["news_impact_reach"]`
- [ ] Update `routers/alerts.py`: load `ClientDNA.temperament` when fetching alerts (or switch sort to DB `ORDER BY rank_score DESC NULLS LAST`)
- [ ] Add `POST /admin/seed/rank` to `admin.py` + import `rank_alerts`; update docstring with TASK-034
- [ ] Smoke-test: `seed/alerts` → `seed/rank` → `GET /clients/{id}/alerts` — CRITICAL dna_conflict for anxious client should appear first
- [ ] Idempotency test: call `seed/rank` twice, assert same `rank_score` values
- [ ] Follow CLAUDE.md: NEVER add a second Alert model; NEVER duplicate enums; reuse existing patterns

### Risk Analysis
- **Risk Level**: LOW
- **Main Risks**:
  - *Migration 0008 applied before Alert model update:* Column exists in DB but SQLAlchemy doesn't know → Alembic autogenerate sees drift. **Mitigation:** update `models/derived.py` and migration in one commit; apply migration first in Docker.
  - *TASK-032 not complete when 034 runs:* `seed/rank` finds 0 alerts. **Mitigation:** rank loader degrades to 0 gracefully (no rows to update → returns `{"clients_processed":N, "alerts_ranked":0}`).
  - *`ClientDNA.temperament` is None for synthetic clients:* `emotional_multiplier` returns 1.0 safely.
  - *TASK-033 noise filter removes one of the TRADE/REACH_OUT pair:* Unlikely — TASK-033 deduplicates by `alert_class + event_cluster_id`, not by `action_type`. Coordinate with TASK-033 if dedup key includes action_type.

### Estimated Effort
- Original: **S**
- Adjusted: **S** — one new module (~80 lines), one small migration, targeted edits to alerts.py + alerts router. Formula is arithmetic (no LLM, no external calls). Main work is the multi-action-type news change + migration.
