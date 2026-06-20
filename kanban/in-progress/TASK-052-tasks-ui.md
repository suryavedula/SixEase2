# TASK-052: Tasks tab UI and lifecycle

**Status:** IN-PROGRESS · **Epic:** EPIC-12 · **Priority:** P1 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Tasks tab in the Action Center: list with mode/status, auto-run results, promote/assign/discard actions, review gate before any outward action.

## Acceptance Criteria
- [ ] tasks listed with mode + status
- [ ] auto results viewable; RM review gate (TK6)
- [ ] promote-to-proposal / assign actions

## Dependencies
TASK-036, TASK-049, TASK-051

## Refs
Requirements §19.2 TK6

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Components:** `TasksList.tsx` + `TaskCard` (TASK-049) — already renders mode/status chips, age, source, "Open" button. Needs result panel + action buttons. `ActionCenter.tsx` (TASK-036) — Tasks tab already renders `<TasksList tasks={tasks}>`. `AppShell.tsx` — already fetches tasks cross-client from all book clients and passes them to ActionCenter.
- **Services:** `patchTaskStatus(clientId, taskId, {status, result})` in `frontend/src/api/tasks.ts` — covers Assign (→ running), Discard (→ closed) transitions. `getClientTasks` — already fetched on mount.
- **APIs:** `PATCH /clients/{id}/tasks/{task_id}` — lifecycle transitions with optional `result` JSONB (TASK-049). `GET /clients/{id}/tasks` — full task list including `result` field. No new backend endpoints needed.
- **Database:** `tasks` table — `status` (created/running/done/closed), `execution_mode` (Auto/Manual), `result` (JSONB), `source` (alert/note/promise), `alert_id`. Fully provisioned by migration 0001.
- **Enums:** `ExecutionMode.AUTO/MANUAL`, `TaskStatus.CREATED/RUNNING/DONE/CLOSED` in `app/models/enums.py`.
- **Review gate (TK6):** Already enforced by the backend PATCH lifecycle (`created → running → done → closed`); the RM clicking "Promote" is the explicit review gate — nothing reaches the canvas automatically.

### Dependency Status
- **TASK-049** (Task model + queue): IN-PROGRESS but fully implemented — router, typed frontend client, TasksList, ActionCenter wiring, AppShell fetch all done.
- **TASK-036** (Action Center): IN-PROGRESS but fully implemented — Tasks tab renders TasksList via `tasks` prop.
- **TASK-051** (Research routine / auto-run cited brief): BACKLOG — the `result` JSONB schema isn't finalized yet. The UI should render a generic result viewer (show `result.summary` if present, fallback to `JSON.stringify` preview), forward-compatible with whatever TK4/TK5 produces.

### Dependencies Required
- Frontend packages: none new — React 19 + Tailwind v4 already installed
- Backend packages: none
- Database migrations: none
- Docker services: none

### Impact Assessment

#### Files to Modify
- `frontend/src/components/widgets/TasksList.tsx`: extend `TaskCard` — add result panel (expandable, shown when `status === "done" && task.result`), running spinner, action buttons (Assign / Promote / Discard); extend `TasksListProps` with `onAssign`, `onPromote`, `onDiscard` callbacks
- `frontend/src/components/shell/ActionCenter.tsx`: add `onTaskAssign`, `onTaskPromote`, `onTaskDiscard` to `ActionCenterProps`; pass through to `<TasksList>`
- `frontend/src/components/shell/AppShell.tsx`: add `handleTaskAssign` (calls `patchTaskStatus → running`, updates local `tasks` state), `handleTaskDiscard` (→ closed), `handleTaskPromote` (pushes result widget to `specs`); pass all three to ActionCenter

#### No files to create
All infrastructure is already in place from TASK-049/036.

#### Components Affected
- `TasksList.tsx` / `TaskCard`: **HIGH** — result panel + action buttons are the core deliverable
- `ActionCenter.tsx`: **LOW** — additive props only, no logic change
- `AppShell.tsx`: **MEDIUM** — three new lifecycle handlers + optimistic state updates

#### API Changes
- None. PATCH endpoint from TASK-049 already handles all transitions.

#### Database Changes
- None.

### Action Button Spec
| Task state | Buttons shown | What it does |
|---|---|---|
| `created` + Manual | **Assign** + Discard | Assign: PATCH → running; Discard: PATCH → closed |
| `created` + Auto | Discard only | Auto tasks self-run; Discard: PATCH → closed |
| `running` | _(spinner)_ + Discard | Discard: PATCH → closed |
| `done` + has result | **Promote** + Discard | Promote: push result to canvas; Discard: PATCH → closed |
| `done` + no result | Open + Discard | Open client view; Discard: PATCH → closed |
| `closed` | — | Terminal; no actions |

### Promote-to-Proposal (TK6 Review Gate)
When the RM clicks **Promote**, `AppShell.handleTaskPromote`:
1. Calls `patchTaskStatus(clientId, taskId, {status: "closed"})` to mark reviewed/consumed.
2. Pushes a `WidgetSpec` to `specs` — initially `{component: "HoldingsTable", props: {clientId}}` as a placeholder until the research-brief widget (TASK-051) exists. The spec type can be extended to `{component: "TaskBrief", props: {clientId, brief: task.result}}` once registered.

### Result Panel (TK4/TK5)
Shown when `status === "done" && task.result`:
- Collapsed by default; expand on click (chevron toggle).
- Render `result.summary` if present (string), else show compact JSON preview (first 200 chars).
- Forward-compatible: once TASK-051 lands, `result` will include `citations[]` — the panel can render them when present without breaking the generic fallback.

### Implementation Checklist
- [ ] Extend `TasksListProps` with `onAssign`, `onPromote`, `onDiscard` (all `(task: TaskWithClient) => void`)
- [ ] `TaskCard`: add running spinner (animate-spin) when `status === "running"`
- [ ] `TaskCard`: add collapsible result panel when `status === "done" && task.result`
- [ ] `TaskCard`: render action buttons per state table above
- [ ] `ActionCenter.tsx`: thread `onTaskAssign`, `onTaskPromote`, `onTaskDiscard` props → TasksList
- [ ] `AppShell.tsx`: `handleTaskAssign` — `patchTaskStatus → running` + optimistic state update
- [ ] `AppShell.tsx`: `handleTaskDiscard` — `patchTaskStatus → closed` + remove from local tasks
- [ ] `AppShell.tsx`: `handleTaskPromote` — close task + push spec to canvas
- [ ] TypeScript clean (`tsc -b --noEmit` passes)
- [ ] Reuse `MODE_CHIP` / `STATUS_CHIP` maps already in TasksList — do not duplicate
- [ ] Follow existing button style patterns from `AlertCard` (Snooze / primary action)

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *TASK-051 result schema unknown* → mitigated by generic result panel that works with any JSONB; forward-compatible when citations arrive.
  - *Promote placeholder widget* → HoldingsTable is a valid stand-in for demo; real TaskBrief widget is TASK-051 scope.
  - *Optimistic state vs. server* → patchTaskStatus is async; update local state after await (not before) to avoid flicker on error.

### Estimated Effort
- Original: S
- Adjusted: S — all backend + data fetching infrastructure is done; this is a self-contained frontend extension of existing TaskCard + prop threading.
