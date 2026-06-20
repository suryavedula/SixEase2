# TASK-035: Alert lifecycle and calibration API

**Status:** DONE · **Epic:** EPIC-08 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20 · **Completed:** 2026-06-20

## Description
Lifecycle: surface, review, act, dismiss, snooze, convert-to-task. Persist status; dismissals feed a calibration signal. Read/update API.

## Acceptance Criteria
- [x] status transitions persisted
- [x] dismissals recorded for calibration (UC-26)
- [x] convert-to-task creates a Task

## Dependencies
TASK-032, TASK-049

## Refs
Requirements §15 AL7

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **Alert model** (`backend/app/models/derived.py:173`) — complete with `status: AlertStatus`, `evidence`, `confidence`, `rank_score`. All 5 lifecycle states are already defined in the enum.
- **AlertStatus enum** (`backend/app/models/enums.py:45`) — OPEN, ACTED, DISMISSED, SNOOZED, CONVERTED already declared and reflected in PG enum `alert_status` (migration 0001).
- **Task model** (`backend/app/models/derived.py:207`) — has `alert_id` FK → `alerts.id` (SET NULL) and `source` Text field. Ready for convert-to-task without schema changes on the tasks table.
- **Read endpoint** (`backend/app/routers/alerts.py:50`) — `GET /clients/{client_id}/alerts` with `?status=` and `?alert_class=` filters. Ordering by severity + recency.
- **Frontend alerts API** (`frontend/src/api/alerts.ts`) — `AlertItem` type + `getClientAlerts()` defined. Only read side; write functions absent.
- **Migration chain** — 0001→0008 applied; next slot is 0009.
- **Admin router** (`backend/app/routers/admin.py`) — documents seeding order; `seed/alerts` (TASK-032) already wired.

### Pre-existing bug to be aware of (TASK-032 scope, not fix here)
`loaders/alerts.py` calls `_generate_news_alerts(session, client, emitted_keys)` with 3 args but the function only accepts 2. Same mismatch on `_generate_dna_conflict_alerts`, `_generate_values_drift_alert`, `_generate_quiet_client_alert`. These will raise `TypeError` at runtime on `POST /admin/seed/alerts`. Note this but do not fix here — it belongs in TASK-032.

### Dependencies Required
- **Backend packages** — none new; `fastapi`, `sqlalchemy`, `pydantic` already available
- **Frontend packages** — none new
- **Database migrations** — 0009 (see below)
- **Docker services** — PostgreSQL (existing)

### What Needs to Be Built

#### 1. Migration 0009 — two new nullable columns on `alerts`
```
snoozed_until  DateTime(timezone=True) nullable  — "snooze until when" timestamp
dismissed_reason  Text nullable                  — calibration signal (UC-26)
```
No enum changes needed; all 5 states already exist.

#### 2. `PATCH /clients/{client_id}/alerts/{alert_id}` — status transition
Request body:
```json
{ "status": "snoozed|acted|dismissed|converted", "snoozed_until": "ISO-8601", "dismissed_reason": "text" }
```
Validation rules:
- `snoozed_until` required when `status == "snoozed"`, rejected on any other status
- `dismissed_reason` accepted only when `status == "dismissed"`
- `CONVERTED` status is set by the convert endpoint, not this one (reject CONVERTED here)

#### 3. `POST /clients/{client_id}/alerts/{alert_id}/convert` — convert-to-task
- Sets alert `status = CONVERTED`
- Creates a `Task` row: `client_id`, `alert_id`, `source="alert"`, `execution_mode=MANUAL`, `status=CREATED`, `title` derived from alert `trigger`
- Returns `{ alert_id, task_id }`

#### 4. Frontend `api/alerts.ts` additions
- `patchAlertStatus(alertId, body)` → `PATCH /clients/{client_id}/alerts/{alert_id}`
- `convertAlertToTask(clientId, alertId)` → `POST /clients/{client_id}/alerts/{alert_id}/convert`

### Impact Assessment

#### Files to Modify
- `backend/migrations/versions/0009_alert_lifecycle.py` (new) — adds `snoozed_until` + `dismissed_reason`
- `backend/app/models/derived.py` — add `snoozed_until` + `dismissed_reason` mapped columns to `Alert`
- `backend/app/routers/alerts.py` — add PATCH transition + POST convert endpoints
- `frontend/src/api/alerts.ts` — add `patchAlertStatus()` + `convertAlertToTask()`

#### Components Affected
- `Alert` model — LOW (additive columns, no breaking changes)
- `GET /clients/{client_id}/alerts` — not changed; existing query unaffected
- `ActionCenter.tsx` (TASK-036) — MEDIUM: will consume `patchAlertStatus` when TASK-036 lands; API contract is the coupling point

#### API Changes
- New: `PATCH /clients/{client_id}/alerts/{alert_id}` — status transition
- New: `POST /clients/{client_id}/alerts/{alert_id}/convert` — alert → task

#### Database Changes
- `alerts.snoozed_until` (DateTime, nullable) — snooze duration
- `alerts.dismissed_reason` (Text, nullable) — UC-26 calibration feed
- No index needed on `dismissed_reason`; calibration reads GROUP BY `alert_class` WHERE `status = 'dismissed'`

### Implementation Checklist
- [ ] Write migration 0009 (`snoozed_until`, `dismissed_reason`; revises 0008)
- [ ] Add `snoozed_until` + `dismissed_reason` mapped columns to `Alert` in `derived.py`
- [ ] Add `AlertTransitionRequest` Pydantic model with cross-field validation
- [ ] Implement `PATCH /clients/{client_id}/alerts/{alert_id}` (status validation, 409 on invalid transitions)
- [ ] Add `ConvertResponse` Pydantic model
- [ ] Implement `POST /clients/{client_id}/alerts/{alert_id}/convert` (creates Task, sets CONVERTED)
- [ ] Add `patchAlertStatus()` to `frontend/src/api/alerts.ts`
- [ ] Add `convertAlertToTask()` to `frontend/src/api/alerts.ts`
- [ ] Reuse `get_session`, `get_logger`, `AlertStatus`, `Task`, `TaskStatus`, `ExecutionMode` — no new imports
- [ ] Follow SOLID principles; keep PATCH handler thin, no separate service layer (effort is S)
- [ ] Human-in-the-loop (G1): all transitions are RM-initiated; no auto-dismissal paths

### Risk Analysis
- **Risk Level**: LOW
- **Main Risks**:
  - Transition race: RM patches an alert that's being re-seeded concurrently → mitigation: seed/alerts deletes and re-inserts, so stale patch returns 404; acceptable
  - TASK-032 bug (signature mismatch on `_generate_news_alerts`) means `seed/alerts` currently throws at runtime — dependency is logically done (code written) but functionally broken; this task's PATCH/convert endpoints work independently since they query existing rows
  - TASK-049 (Task model) also still in backlog but `Task` model already in schema — convert-to-task can proceed

### Estimated Effort
- Original: S
- Adjusted: S
- Reason: Everything is in place — enum, model, FK. Only 2 new columns + 2 new endpoints + 2 frontend functions.

---

## Completion Summary (2026-06-20)

### Implemented Features
- ✅ Status transitions persisted via `PATCH /clients/{client_id}/alerts/{alert_id}`
- ✅ `dismissed_reason` stored as UC-26 calibration signal
- ✅ `POST /clients/{client_id}/alerts/{alert_id}/convert` creates Task, sets CONVERTED status

### Technical Changes
- `backend/migrations/versions/0009_alert_lifecycle.py`: adds `snoozed_until` (DateTime tz-aware) + `dismissed_reason` (Text) nullable columns
- `backend/app/models/derived.py`: `snoozed_until` + `dismissed_reason` mapped columns on `Alert`
- `backend/app/routers/alerts.py`: `AlertTransitionRequest` (cross-field Pydantic validator), `PATCH` transition endpoint, `ConvertResponse`, `POST /convert` endpoint
- `frontend/src/api/alerts.ts`: `AlertTransitionRequest` + `ConvertResponse` types, `patchAlertStatus()`, `convertAlertToTask()`

### Code Quality
- SOLID: thin handlers, no service layer (effort S); validation in Pydantic model_validator
- ACID: single `session.commit()` per endpoint; convert-to-task is atomic (task insert + alert status in one commit)
- Reused: `get_session`, `get_logger`, `AlertStatus`, `ExecutionMode`, `TaskStatus`, `Task` — no new imports
- Human-in-the-loop (G1): all transitions are RM-initiated via explicit API call

### Implementation Checklist
- [x] Write migration 0009 (`snoozed_until`, `dismissed_reason`; revises 0008)
- [x] Add `snoozed_until` + `dismissed_reason` mapped columns to `Alert` in `derived.py`
- [x] Add `AlertTransitionRequest` Pydantic model with cross-field validation
- [x] Implement `PATCH /clients/{client_id}/alerts/{alert_id}` (status validation, 409 on invalid transitions)
- [x] Add `ConvertResponse` Pydantic model
- [x] Implement `POST /clients/{client_id}/alerts/{alert_id}/convert` (creates Task, sets CONVERTED)
- [x] Add `patchAlertStatus()` to `frontend/src/api/alerts.ts`
- [x] Add `convertAlertToTask()` to `frontend/src/api/alerts.ts`
