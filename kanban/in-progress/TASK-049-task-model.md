# TASK-049: Task model and queue

**Status:** IN-PROGRESS · **Epic:** EPIC-12 · **Priority:** P1 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Task entity + queue with execution mode Auto or Manual, status, source (alert/note/promise), result. Tasks tab feeds from here.

## Acceptance Criteria
- [ ] tasks created from alerts/notes/promises (TK1)
- [ ] Auto vs Manual mode set (TK2)
- [ ] lifecycle states persisted

## Dependencies
TASK-004, TASK-005

## Refs
Requirements §19.2 TK1/TK2

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency status
- **TASK-004** (DB schema + migrations) — in `review/`, fully implemented. `tasks` table exists
  with `client_id`, `alert_id`, `title`, `source`, `execution_mode` (`ExecutionMode` enum:
  Auto/Manual), `status` (`TaskStatus` enum: created/running/done/closed), `result` (JSONB).
  `ix_tasks_client_status` index exists. **No schema changes needed.**
- **TASK-005** (Redis/MinIO) — in `in-progress/`, fully implemented. `enqueue(queue, payload)`
  helper in `app/redis_client.py` is ready for the task queue backbone (TK2 Auto dispatch).
- **Alert→Task conversion** — already built as part of TASK-035 (`alerts.py`):
  `POST /clients/{id}/alerts/{alert_id}/convert` creates a Task with `source="alert"`,
  `execution_mode=MANUAL`. This satisfies TK1 for the alert source.

### Existing Resources Found
- **ORM model:** `app/models/derived.Task` — all required columns exist; TASK-004 is done.
- **Enums:** `ExecutionMode.AUTO/MANUAL`, `TaskStatus.CREATED/RUNNING/DONE/CLOSED` in `app/models/enums.py`.
- **Redis queue:** `enqueue(queue, payload)` / `dequeue(queue)` in `app/redis_client.py` — backbone for Auto dispatch.
- **Alert→Task bridge:** `POST …/convert` in `app/routers/alerts.py` — TK1 alert source covered.
- **Frontend:** `convertAlertToTask()` in `frontend/src/api/alerts.ts` wires the convert endpoint.
- **ActionCenter Tasks tab:** exists in `ActionCenter.tsx` but currently shows filtered alerts, not real Task rows.
- **Pattern to follow:** `app/routers/alerts.py` (read list + PATCH transitions).

### What TASK-049 builds
1. `backend/app/routers/tasks.py` — GET per-client task list, POST manual creation (note/promise source), PATCH lifecycle transitions + Auto enqueue.
2. Register `tasks` router in `backend/app/main.py`.
3. `frontend/src/api/tasks.ts` — typed API client mirroring `alerts.ts`.
4. `frontend/src/components/widgets/TasksList.tsx` — task cards with mode/status badges.
5. Update `frontend/src/components/shell/ActionCenter.tsx` — Tasks tab uses real Task rows via `tasks` prop.
6. Update `frontend/src/components/shell/AppShell.tsx` — fetch cross-client tasks alongside alerts.

### Dependencies Required
- Frontend packages: none (Tailwind already present)
- Backend packages: none (all deps installed)
- Database migrations: **none** — `tasks` table exists from migration 0001
- Docker services: `redis` (TASK-005, already running)

### Impact Assessment
#### Files to Create
- `backend/app/routers/tasks.py`
- `frontend/src/api/tasks.ts`
- `frontend/src/components/widgets/TasksList.tsx`

#### Files to Modify
- `backend/app/main.py` — add `tasks` router import + include
- `frontend/src/components/shell/ActionCenter.tsx` — Tasks tab → real TaskItem list
- `frontend/src/components/shell/AppShell.tsx` — fetch tasks for all clients

#### Components Affected
- `ActionCenter.tsx`: **MEDIUM** — Tasks tab changes from alert-filter to Task rows; props extended with `tasks`
- `AppShell.tsx`: **LOW** — additive: fetch + pass tasks alongside existing alerts fetch
- `alerts.py` convert endpoint: **NONE** — untouched, already satisfies TK1 alert source

#### API Changes
- New: `GET /clients/{id}/tasks?status=&mode=` — per-client task list
- New: `POST /clients/{id}/tasks` — create task from note or promise
- New: `PATCH /clients/{id}/tasks/{task_id}` — lifecycle transition + Auto enqueue

#### Database Changes
- None — tasks table fully provisioned by TASK-004.

### Implementation Checklist
- [ ] Reuse `app/models/derived.Task` — do not redefine
- [ ] Follow `alerts.py` pattern (Pydantic response models, `get_session` dep, structlog)
- [ ] Auto tasks → enqueue to `"task_queue"` Redis list on creation (TK2)
- [ ] PATCH transitions validate source→target lifecycle (created→running, running→done/closed)
- [ ] Frontend TaskItem mirrors backend response exactly
- [ ] ActionCenter Tasks tab shows `tasks` prop, not filtered alerts
- [ ] AppShell fetches tasks cross-client same way it fetches alerts

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *Auto task runner doesn't exist yet* (TASK-043/044) → enqueue now, worker lands later; queue is durable in Redis.
  - *ActionCenter prop surface grows* → additive only; no existing props change.

### Estimated Effort
- Original: **S**
- Adjusted: **S** — schema is done; this is purely a thin router + frontend wiring layer.
