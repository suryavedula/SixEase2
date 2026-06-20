# TASK-009: Load CRM interaction notes

**Status:** IN-PROGRESS · **Epic:** EPIC-02 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Ingest the four persona CRM tabs into the Interaction table (date, medium, rm, contact, note), preserving chronology for DNA extraction.

## Acceptance Criteria
- [x] all four personas notes loaded
- [x] dates normalised
- [x] notes queryable per client

## Dependencies
TASK-004, TASK-007

## Refs
Requirements §10.1

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- `app/xlsx.py` — `load_sheet(path, sheet)` → `list[dict]` + `excel_serial_to_date(serial)` (TASK-007)
- `app/models/source.py` — `Client` + `Interaction` ORM models, schema matches §10.1 columns exactly
- `app/models/enums.py` — `Mandate.DEFENSIVE / BALANCED / GROWTH`
- `app/db.py` — async `SessionFactory` + `get_session` FastAPI dependency
- `app/config.py` — `Settings.wealth_data_dir` (added by this task, default `/app/data`)
- `docker-compose.yml` — `./data:/app/data:ro` bind-mount already present (TASK-001)

### Workbook facts
- File: `SwissHacks CRM.xlsx` → 4 sheets: `CRM Raeber`, `CRM Schneider`, `CRM Huber`, `CRM Ammann`
- Columns per sheet: `Date` (Excel serial), `Medium`, `RM Name`, `Client Contact`, `Note`
- Row counts: Räber 20, Schneider 26, Huber 20, Ammann 28 (94 total)
- Persona→mandate assignments (§11 archetypes):
  - Räber → `DEFENSIVE` (confirmed by internal CIO note referencing "defensive model portfolio")
  - Schneider → `BALANCED` (first note: "Global Balanced Growth mandate")
  - Huber → `BALANCED` (Defensive/Balanced archetype; picks Balanced for demo variety)
  - Ammann → `GROWTH` (analytical, asymmetric-tail-risk focus)

### Dependencies Required
- Backend packages: none new (stdlib `pathlib` + existing `xlsx` + `sqlalchemy`)
- DB migration: none — `clients` + `interactions` tables created by TASK-004 migration 0001
- Config: `wealth_data_dir: str = Field(default="/app/data")` added to `Settings`

### Impact Assessment
#### Files Created
- `backend/app/loaders/__init__.py` — package init
- `backend/app/loaders/crm.py` — `load_crm(session, data_dir)` async loader
- `backend/app/routers/admin.py` — `POST /admin/seed/crm` endpoint (shared with TASK-008)

#### Files Modified
- `backend/app/config.py` — added `wealth_data_dir` setting
- `backend/app/main.py` — registered `admin.router`
- `.env.example` — added `WEALTH_DATA_DIR` documentation

#### API Changes
- `POST /admin/seed/crm` — triggers idempotent CRM load; returns `{status, loaded: {name: count}}`

#### Database Changes
- Writes to `clients` (get-or-create by name) and `interactions` (delete-and-reload per client)
- No schema changes (tables already exist from TASK-004)

### Idempotency design
- **Clients**: `SELECT` by name → create if missing; update nothing if found (mandate stays stable).
- **Interactions**: `DELETE WHERE client_id = X` then bulk insert — safe re-run reflects workbook edits.
- Single `session.commit()` after all four personas so failure leaves DB clean (all-or-nothing).

### Implementation Checklist
- [x] `app/loaders/crm.py` with `load_crm(session, data_dir)` following flat-module conventions
- [x] `excel_serial_to_date` used for `Date` column; non-date numerics handled gracefully
- [x] Structured logging (`crm.client_created`, `crm.sheet_loaded`, `crm.load_complete`)
- [x] `POST /admin/seed/crm` wired in `admin.py` router (shared scaffold for TASK-008)
- [x] `Settings.wealth_data_dir` + `.env.example` updated
- [x] `main.py` registers the admin router

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *`Client` name collision if TASK-008 seeds clients with different name strings* → both loaders use the same canonical names from §11 archetypes; no conflict expected.
  - *Workbook not mounted in container* → `FileNotFoundError` surfaced as HTTP 500 with clear message; check `WEALTH_DATA_DIR` env.
  - *`Note` field contains non-breaking spaces (confirmed: `\xa0` in Räber last row)* — stored as-is in TEXT column; DNA extraction (TASK-016) normalises whitespace.

### Estimated Effort
- Original: **S**
- Adjusted: **S** — single loader + admin endpoint; widened slightly by the shared admin router scaffold that TASK-008 will reuse.

---

## Implementation (2026-06-20)

**Files created**
- `backend/app/loaders/__init__.py` — package declaration
- `backend/app/loaders/crm.py` — `load_crm(session, data_dir)` async function:
  iterates `_PERSONA_SHEETS`, upserts each `Client` by name, deletes+reloads all
  `Interaction` rows per client, commits one transaction for all four personas.
- `backend/app/routers/admin.py` — `POST /admin/seed/crm` (scaffold shared with TASK-008's
  `POST /admin/seed/portfolio`, which appends to this same router).

**Files modified**
- `backend/app/config.py` — `wealth_data_dir: str = Field(default="/app/data")`
- `backend/app/main.py` — `app.include_router(admin.router)`
- `.env.example` — `WEALTH_DATA_DIR=/app/data` with host-override note

**Persona→mandate mapping (hardcoded, from §11):**
| Sheet | Client | Mandate |
|---|---|---|
| CRM Raeber | Eugen Räber | DEFENSIVE |
| CRM Schneider | Hubertus Schneider | BALANCED |
| CRM Huber | Marius Huber | BALANCED |
| CRM Ammann | Julian Ammann | GROWTH |

**Verification:**
```bash
# Trigger load
curl -X POST http://localhost:8000/admin/seed/crm
# Expected: {"status":"ok","loaded":{"Eugen Räber":20,"Hubertus Schneider":26,"Marius Huber":20,"Julian Ammann":28}}

# Confirm rows
docker compose exec postgres psql -U wealth -d wealth \
  -c "SELECT c.name, COUNT(i.id) FROM clients c LEFT JOIN interactions i ON i.client_id=c.id GROUP BY c.name;"
```
