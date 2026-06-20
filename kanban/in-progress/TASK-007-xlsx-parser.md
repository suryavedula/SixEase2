# TASK-007: Stdlib XLSX parser

**Status:** IN-PROGRESS · **Epic:** EPIC-02 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Port the stdlib zipfile+XML xlsx reader into the backend as a utility (no pandas/openpyxl). Parse sharedStrings + sheets into row dicts.

## Acceptance Criteria
- [ ] reads both workbooks into typed rows
- [ ] handles Excel serial dates conversion
- [ ] unit-checked against known cell values

## Dependencies
TASK-002

## Refs
Requirements §10 (data inventory), CLAUDE.md (no pandas)

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **No existing xlsx/sharedStrings code anywhere in the repo** (grep across `*.py`/`*.ts`):
  the only mentions are CLAUDE.md and this ticket. This is greenfield — nothing to extend.
- **Backend skeleton is ready** (TASK-002, in-progress, all ACs checked): `backend/app/` is a
  flat-module package — `config.py`, `logging.py`, `db.py`, `storage.py`, `redis_client.py`,
  plus `routers/` and `models/`. New utility modules sit as flat siblings under `app/`.
- **Module conventions to mirror** (from `storage.py` / `logging.py`):
  - Module docstring opens with the task/epic tag, e.g. `(TASK-007, EPIC-02)`.
  - Structured logging via `from app.logging import get_logger; log = get_logger(__name__)`
    with dotted event keys (`storage.bucket_created`) — use `xlsx.parsed` etc.
  - Pure-stdlib, synchronous helpers with explicit return types; no async needed (parsing is
    CPU-bound, called from setup/seed paths not the hot request loop).
- **Datasets present**: `data/SwissHacks CRM.xlsx` (31 KB) and
  `data/SwissHacks Portfolio Construction.xlsx` (181 KB). Sheet/column layout fully documented
  in Requirements §10.1–§10.4 — consult before re-parsing.

### Dependencies Required
- **Frontend packages:** none (backend-only task).
- **Backend packages:** **none to add.** Use only `zipfile`, `xml.etree.ElementTree`,
  `datetime` from the stdlib. `requirements.txt` deliberately has **no pandas/openpyxl** —
  keep it that way (CLAUDE.md hard rule).
- **Test tooling:** `pytest` is **not** in `requirements.txt` and there is **no `backend/tests/`
  directory yet** (DECISION below).
- **Database migrations:** none — this task only reads files into in-memory row dicts. Persisting
  the parsed rows is downstream (CRM/portfolio ingestion tasks).
- **Docker services:** none — pure local file parse.

### Impact Assessment
#### Files to Create
- `backend/app/xlsx.py`: the parser utility (zipfile + ElementTree reader, shared-strings
  resolution, serial-date conversion, sheet → `list[dict]` with header row as keys).
- `backend/tests/test_xlsx.py`: unit check against known cell values from both workbooks.
- (if pytest is chosen) `backend/tests/__init__.py` + a `pytest` pin in `requirements.txt`.

#### Files to Modify
- `backend/requirements.txt`: **only** if pytest is adopted for the test AC (see DECISION).
- No existing source file is touched — additive, zero breaking-change risk.

#### Components Affected
- None currently. Future consumers (CRM DNA extraction, portfolio/drift engine, CIO swap
  universe) will import this module — design the API for them: `LOW` impact today.

#### API Changes
- None. No HTTP endpoint, no contract, no WebSocket message.

#### Database Changes
- None.

### Suggested Module Shape (for the implementer)
```python
# backend/app/xlsx.py
def load_sheet(path: str | Path, sheet: str) -> list[dict]   # header row → dict keys
def load_workbook(path: str | Path) -> dict[str, list[dict]] # {sheet_name: rows}
def excel_serial_to_date(serial: float) -> date              # epoch 1899-12-30
```
Implementation notes / the things that bite:
- **XLSX namespace:** worksheet/sharedStrings XML use the spreadsheetml namespace —
  strip or match `{http://schemas.openxmlformats.org/spreadsheetml/2006/main}` on every tag.
- **Shared strings:** cells with `t="s"` hold an *index* into `xl/sharedStrings.xml`; resolve
  it. Cells with `t="str"`/`t="inlineStr"`/numeric are inline.
- **Sheet name → file:** map via `xl/workbook.xml` (`<sheet name= r:id=>`) +
  `xl/_rels/workbook.xml.rels`; do **not** assume `sheetN.xml` order matches tab order.
- **Sparse rows / gaps:** cells carry an `r` ref (e.g. `B7`); blank cells are simply absent —
  decode column letters to index so columns don't shift.
- **Dates are Excel serials** (§10.3): convert with epoch `1899-12-30` (accounts for the Lotus
  1900-leap-year bug). Only the `Date` column in CRM tabs and any portfolio `As Of`/`Rating
  Since` columns are dates — don't blanket-convert numeric cells.
- **Bonds price at par / blank Valor** (§10.3) — that's data semantics for downstream, not the
  parser's concern; the parser returns raw cell values.

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] New `app/xlsx.py` follows the flat-module + docstring-tag + `get_logger` conventions
- [ ] Pure stdlib only — no pandas/openpyxl, no new runtime deps
- [ ] Resolve sheets by name via `workbook.xml` rels (not positional `sheetN.xml`)
- [ ] Decode cell `r` refs so sparse/blank cells don't shift columns
- [ ] Serial-date conversion isolated in one tested helper (epoch 1899-12-30)
- [ ] Generic API (`load_sheet`/`load_workbook`) so CRM + portfolio consumers reuse unchanged
- [ ] Proper error handling (bad path, missing sheet, malformed zip) with clear messages
- [ ] Self-documenting; type-hinted signatures

### Verification Targets (known cell values for the test AC)
Pin the test to stable, documented anchors from §10:
- CRM workbook → 4 tabs exactly: `CRM Raeber`, `CRM Schneider`, `CRM Huber`, `CRM Ammann`;
  header row `Date · Medium · RM Name · Client Contact · Note`.
- Portfolio workbook → 10 sheets incl. `Portfolio Strategies`, `CIO Recommendation List`
  (172 data rows), `Sample Portfolio Defensive/Balanced/Growth`.
- A serial-date round-trip assertion (a known CRM `Date` serial → expected `date`).
- (Confirm the exact anchor cells by parsing once during implementation, then freeze them.)

### Risk Analysis
- **Risk Level:** LOW (additive utility, no deps, no schema/API surface).
- **Main Risks:**
  - *XLSX edge cases (namespaces, sparse cells, shared-string indices) produce silently wrong
    rows* → mitigate with the known-value unit check across **both** workbooks, not just one.
  - *Date conversion off-by-one (1900 leap bug)* → dedicated serial→date helper with an
    explicit round-trip test.
  - *Test tooling drift* → resolve the DECISION below before writing the test file.

### DECISION NEEDED — test harness
No `backend/tests/` and no `pytest` exist yet. Two options:
1. **stdlib `unittest`** in `backend/tests/test_xlsx.py` — zero new deps, honours the
   "no unnecessary deps" ethos. *(Recommended for this S-task.)*
2. **add `pytest`** to `requirements.txt` — nicer ergonomics, but introduces the project's
   first test dependency and should be a deliberate, project-wide call.
Default to (1) unless the team wants pytest as the standard now.

### Estimated Effort
- Original: S
- Adjusted: S (unchanged) — single self-contained module + one test file; the only judgement
  call is the test-harness DECISION above.
