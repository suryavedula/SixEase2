# TASK-036: Action Center UI

**Status:** IN-PROGRESS · **Epic:** EPIC-08 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Right-drawer Action Center: bell badge, Mark-All-Read, category tabs (All/Urgent/Clients/Market/Compliance/Tasks), alert cards with severity chip, due/age, body, primary+secondary actions, dismiss. Clicking opens the case in the canvas.

## Acceptance Criteria
- [ ] categorised queue renders from API
- [ ] actions trigger canvas views / lifecycle
- [ ] matches Project-Overview prototype

## Dependencies
TASK-003, TASK-035

## Refs
Requirements §15 AL9, UI-5

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Components:** `ActionCenter.tsx` shell chrome already built in TASK-003 (tabs, header, empty state — seam explicitly left for this task). `AppShell.tsx`, `Canvas.tsx`, `Header.tsx` all exist and need wiring.
- **Services:** `GET /clients/{client_id}/alerts` fully live (backend/app/routers/alerts.py). Returns `id, alert_class, action_type, severity, trigger, why, suggested_action, status, confidence, evidence, created_at`. Sorted by severity then recency.
- **APIs:** `GET /book` live — provides all client UUIDs + names for aggregating the book-level alert queue.
- **Database:** `Alert` model with enums: Severity (Critical/Attention/FYI), AlertStatus (open/acted/dismissed/snoozed/converted), ActionType (Trade/ReachOut/Acknowledge/Watch), alert_class (drift_breach, stale_sell, news_impact, good_news, panic, dna_conflict, values_drift, quiet_client, overdue_promise, behavioural_guardrail).
- **Utilities:** `apiGet` in `src/api/client.ts` — reused for new alerts client.

### Dependencies Required
- Frontend packages: none new — React 19 + Tailwind v4 already installed
- Backend packages: none
- Database migrations: none
- Docker services: none

### Impact Assessment

#### Files Modified
- `frontend/src/api/alerts.ts` (NEW): typed client for `GET /clients/{id}/alerts`; exports `AlertItem`, `AlertsResponse`, `AlertWithClient`, `getClientAlerts`
- `frontend/src/components/shell/ActionCenter.tsx`: full rewrite — alert cards, live category filtering, badge, dismiss, onOpenClient callback
- `frontend/src/components/shell/AppShell.tsx`: lifts `activeClientId` state (was local to Canvas); adds `useEffect` to fetch book → all client alerts; wires `alertCount`, `onDismiss`, `onMarkAllRead`, `onOpenClient` to ActionCenter
- `frontend/src/components/shell/Canvas.tsx`: `clientId`/`onClientChange` become props instead of local state (trivial lift to enable cross-component navigation)

#### Components Affected
- ActionCenter: HIGH — full alert list implementation
- AppShell: MEDIUM — state lift + data fetching
- Canvas: LOW — props only, no logic change
- Header: NONE — `alertCount` prop already wired

#### API Changes
- None. Only adds GET calls to existing endpoints.

#### Database Changes
- None.

### Category Mapping (alert_class → tab)
- **Clients:** quiet_client, overdue_promise, good_news
- **Market:** news_impact, panic, drift_breach, stale_sell
- **Compliance:** dna_conflict, values_drift, behavioural_guardrail
- **Urgent:** severity === Critical (cross-category)
- **Tasks:** action_type === Trade or ReachOut

### Implementation Checklist
- [x] `src/api/alerts.ts` — typed API client, `AlertWithClient` interface
- [x] `AppShell.tsx` — lift clientId, fetch book + all alerts on mount, wire alertCount
- [x] `Canvas.tsx` — accept clientId/onClientChange as props
- [x] `ActionCenter.tsx` — AlertCard component: severity chip, client name, age, body (why/trigger), primary (Rebalance/Draft Message/Acknowledge/Watch) + secondary (Snooze) actions, dismiss (×)
- [x] Category tabs active state with per-category filtering
- [x] Bell badge live from fetched alert count
- [x] Mark-All-Read (optimistic clear; server-side lifecycle via TASK-035)
- [x] Dismiss (optimistic removal; server-side lifecycle via TASK-035)
- [x] Clicking client name → sets activeClientId → Canvas opens portfolio view
- [x] TypeScript clean (`tsc -b --noEmit` passes)
- [ ] Lifecycle mutations (act, snooze, convert-to-task) — blocked on TASK-035 API
- [ ] Snooze duration picker — deferred to TASK-035

### Dependency Notes
- **TASK-003:** Functionally complete (shell live, seam left for this task). Not in done/ but unblocking is safe.
- **TASK-035:** Alert lifecycle API (PATCH endpoint for status transitions). Still BACKLOG. This task delivers read + optimistic UI; TASK-035 must wire server persistence for dismiss/snooze/convert. Primary/Rebalance action button is visual-only until TASK-038 (trade execution) exists.

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *No global /alerts endpoint* → mitigated by fetching per-client via book (4 clients = 4 parallel requests, negligible at demo scale).
  - *Lifecycle mutations not yet persisted* → mitigated by optimistic state; clearly scoped to TASK-035.
  - *No "open case" deep-link yet* → clicking client name opens the UUID-based portfolio view (TASK-025 smoke-test seam); full command-driven canvas navigation arrives in TASK-041/042.

### Estimated Effort
- Original: M
- Adjusted: M (unchanged) — most infrastructure was already built in TASK-003; implementation is self-contained UI + data wiring.
