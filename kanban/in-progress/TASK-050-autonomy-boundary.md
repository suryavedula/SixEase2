# TASK-050: Autonomy-boundary enforcement

**Status**: IN-PROGRESS · **Epic:** EPIC-12 · **Priority:** P1 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned**: Unassigned
**Started**: 2026-06-20
**Analysis Completed**: 2026-06-20

## Description
Enforce that only read-only/analysis/research/draft-prep tasks may auto-run; outward/irreversible actions (contact client, place order, send) are forced Manual and require RM action.

## Acceptance Criteria
- [ ] outward/irreversible tasks cannot auto-run (TK3)
- [ ] classification rule documented and tested
- [ ] violations blocked + logged

## Dependencies
TASK-049

## Refs
Requirements §19.2 TK3, G1

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Enums**: `ExecutionMode` (Auto/Manual) and `TaskStatus` already live in `backend/app/models/enums.py:64–78`. The docstring already references TK3.
- **Task model**: `Task` ORM class already exists in `backend/app/models/derived.py:209–232` with `execution_mode` column (TK2 ✓).
- **DB schema**: `tasks` table and `execution_mode` PG enum created in migration `0001_initial_schema.py`. **No new migration needed.**
- **Existing safe hardcode**: `backend/app/routers/alerts.py:359` hardcodes `ExecutionMode.MANUAL` on alert→task conversion — already correct by design.
- **Logging infra**: structured `get_logger` pattern in `backend/app/logging.py` — reuse for violation logging (TK5).
- **Test runner**: `pytest` + `pytest-asyncio` already in `requirements.txt`; existing tests in `backend/tests/`.

### Dependencies Required
- **Frontend packages**: none — this is pure backend logic
- **Backend packages**: none new — all in requirements.txt
- **Database migrations**: none — `tasks` table + `execution_mode` column exist in 0001
- **Docker services**: none new

### Impact Assessment

#### Files to Create/Modify
- `backend/app/loaders/task_classify.py` *(new)*: the single-source-of-truth classification rule. Exports `classify_execution_mode(task_kind: str) -> ExecutionMode` and `assert_auto_eligible(task_kind: str) -> None`.
- `backend/app/models/enums.py`: add `TaskKind` enum — the closed vocabulary of task kinds, so callers pass a typed value not a raw string.
- `backend/tests/test_autonomy_boundary.py` *(new)*: unit tests covering all Auto-eligible kinds, all Manual-forced kinds, and the violation-log path.
- `backend/app/routers/alerts.py`: no change needed — already forces MANUAL. Add import of `TaskKind` when TASK-049 introduces more creation paths.

#### Components Affected
- `backend/app/models/enums.py`: LOW — additive only (new enum, no existing values changed)
- `backend/app/loaders/task_classify.py`: NEW — pure function, no DB/IO
- `backend/app/routers/alerts.py`: LOW — no logic change; `task_classify` imported and called as guard when TASK-049 adds general task-creation
- Future TASK-049 task-creation router: HIGH — must call `classify_execution_mode` to set `execution_mode` on every new task row

#### API Changes
- None for TASK-050 itself. TASK-049's task-creation endpoint will consume `classify_execution_mode` but that endpoint doesn't exist yet.

#### Database Changes
- None — schema is complete.

### Classification Rule (TK3)

**Auto-eligible kinds** (read-only / analysis / research / draft-prep):
| TaskKind | Auto reason |
|---|---|
| `research` | read-only: web / news / SIX / CRM query; result is a cited brief |
| `news_gather` | read-only: event-registry fanout, no writes |
| `swap_candidates` | analysis: compute fit scores; no order placed |
| `draft_prep` | draft text generated; RM must approve before send (MSG step, not the send itself) |
| `analysis` | generic read-only computation |

**Manual-forced kinds** (outward / irreversible):
| TaskKind | Why Manual |
|---|---|
| `contact_client` | outward action — sends a message/email to the client (G1) |
| `place_order` | irreversible financial action |
| `send_message` | outward — delivers a channel message |
| `crm_writeback` | persistent external write (client record) |

**Default**: any unknown kind → `Manual` (safe default; violation logged).

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Reuse `get_logger` from `app.logging` for violation log (do not add a print/custom logger)
- [ ] Reuse `ExecutionMode` from `app.models.enums`; add `TaskKind` in same file
- [ ] Keep `task_classify.py` pure (no DB/IO): just `dict` lookup + log on violation
- [ ] Follow existing test pattern (`pytest`, sync unit tests — no asyncio needed here)
- [ ] No new packages, no migration, no frontend changes
- [ ] Self-documenting: `TaskKind` docstring IS the classification rule; no separate doc file

### Risk Analysis
- **Risk Level**: LOW
- **Main Risks**:
  - *TASK-049 not done yet*: `task_classify` can be written and tested standalone; it's wired up when TASK-049 lands the task-creation endpoint. Unblock ordering is fine.
  - *Enum value mismatch (migration vs model)*: migration 0001 uses uppercase `"AUTO"/"MANUAL"` but the ORM `ExecutionMode` uses `"Auto"/"Manual"`. Existing code uses the ORM values via SQLAlchemy — confirm `create_type=False` means PG stores the ORM string, not the migration literal. Mitigate: run existing tests against a live DB to confirm no coercion issue.
  - *New `TaskKind` enum* scope-creep: keep it minimal — only the 9 kinds above; unknown kinds map to MANUAL, so future extension is additive.

### Estimated Effort
- Original: S
- Adjusted: S (confirmed — no migration, no API, no frontend, pure logic + tests)
- Reason: Schema and enums already exist from TASK-004; this is only the classifier function and tests.
