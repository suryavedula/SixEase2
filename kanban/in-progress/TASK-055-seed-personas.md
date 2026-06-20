# TASK-055: Seed personas end-to-end + triggers

**Status:** IN-PROGRESS · **Epic:** EPIC-14 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Wire the four real personas through the full pipeline (DNA, holdings, watchlist, alerts, swap, message) and attach each scripted trigger event so every demo path works offline.

## Acceptance Criteria
- [ ] all four personas fully populated end-to-end
- [ ] each has a working scripted trigger (D3)
- [ ] runs without live API dependency

## Dependencies
TASK-009, TASK-016, TASK-026, TASK-032, TASK-038

## Refs
Requirements §7 D1/D3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Loaders (all functional):** `load_portfolio`, `load_crm`, `load_tags`, `extract_dna`, `extract_style_profiles`, `compute_fit`, `compute_swaps`, `enrich_holdings`, `build_watchlists`, `seed_news_triggers`, `generate_alerts`, `compute_drift`, `rank_alerts`, `assemble_fact_sheet`, `render_message_draft`
- **D3 Triggers already scripted:** `backend/app/loaders/news_seed.py` — 4 articles, one per persona (Schneider: AstraZeneca neuro shutdown; Huber: EU Green Bond package; Räber: Intel earnings decline; Ammann: LVMH/Richemont luxury rally)
- **Admin router:** `backend/app/routers/admin.py` — 18 existing seed endpoints, all idempotent
- **Real persona names:** Eugen Räber (Defensive), Hubertus Schneider (Balanced), Marius Huber (Balanced), Julian Ammann (Growth)

### Dependencies Required
- Backend packages: all already in `requirements.txt`
- Docker services: `postgres`, `redis`, `ollama` (for LLM steps 4, 5, 14)
- Data files: `SwissHacks CRM.xlsx`, `SwissHacks Portfolio Construction.xlsx` (in `data/`)

### Impact Assessment

#### Files to Modify
- `backend/app/loaders/style_profile.py`: bug fix — `extract_style_profiles` raises unconditionally when a client has no interactions; must gracefully skip (like `extract_dna`) so the all-clients call works alongside sample portfolio clients
- `backend/app/routers/admin.py`: add `POST /admin/seed/personas` endpoint + import

#### Files to Create
- `backend/app/loaders/personas.py`: 14-step pipeline orchestrator for the 4 real personas

#### Components Affected
- `loaders/style_profile.py`: LOW — pure bugfix, no contract change
- `routers/admin.py`: LOW — additive only (new endpoint)
- `loaders/personas.py`: new file, no existing dependents

#### API Changes
- `POST /admin/seed/personas` (new): runs all 14 steps in order; returns `{"status": "ok", "loaded": {...summary...}}`; HTTP 409 for missing prerequisites, 500 for unexpected errors

#### Database Changes
- None — all tables already exist; this endpoint writes through existing loaders

### Implementation Checklist
- [x] Reuse all existing loaders — no new extraction logic
- [x] Fix `style_profile.py` to gracefully skip clients without interactions/DNA (consistent with `extract_dna` pattern)
- [x] Orchestrate full 14-step pipeline in `personas.py`
- [x] Step 14 (message) is best-effort: skip if no dna_conflict alert, don't fail pipeline
- [x] Log each step completion for observability
- [x] Add `POST /admin/seed/personas` to admin router

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - LLM unavailable (Ollama not running): steps 4, 5, 14 fail — mitigation: clear error propagated; steps 1–3, 6–13 are pure DB/SIX and work without LLM
  - No dna_conflict alerts for a persona: step 14 skipped for that persona — mitigation: logged as warning, rest of pipeline unaffected
  - SIX unavailable: `enrich_holdings` falls back to workbook par-pricing — mitigation: already implemented in TASK-026

### Estimated Effort
- Original: M
- Adjusted: M
- Reason: all loaders exist; task is orchestration + bugfix only
