# TASK-063: Improvement-radar API — book-wide swap-engine sweep

**Status:** IN-PROGRESS · **Epic:** EPIC-10 · **Parent:** TASK-062 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
New endpoint that runs the existing swap/fit engine across **every client portfolio** and returns
a ranked list of clients where a real, CIO-compliant improvement is available — the periodic
("every 2–3 months") "whose portfolio can be improved by their DNA" list.

- For each client: reuse `fit.py` + `swap.py` to compute resolvable conflicts and best-candidate
  `fit_gain` per slot; keep only clients with at least one swap passing the **≥10pp fit-gain gate**
  (no-churn) so the list stays signal, not noise.
- Rank clients by **impact** = `Σ_slots(fit_gain × exposure_chf_in_slot)`; tiebreak by "why now".
- Compute **"why now"**: new CIO-list version since last review, and/or new CRM notes that shifted
  the client's DNA (exclusions/tilts) since the prior sweep.
- Return per client: portfolio_fit (current → projected), resolvable-conflict count, top swaps
  (issuer → candidate, dna_reason, candidate_cio_view, fit_gain), and total improvable CHF.
- **Separate from `/radar` (TASK-059)** — distinct route, distinct ranking (DNA/fit, not
  exposure×magnitude×recency). No shared scorer.

## Acceptance Criteria
- [ ] `GET /book/improvements` (working name) returns clients ranked by improvement impact
- [ ] Only clients with ≥1 swap clearing the ≥10pp fit-gain gate appear
- [ ] Each candidate is CIO-BUY, same sub-asset-class + industry-group, mandate-neutral (reuse engine)
- [ ] "Why now" populated from CIO-list version and/or DNA delta since last review
- [ ] Every number traceable to a data tool; model authors no figures (grounding rule)
- [ ] Clients with conflicts but **no** compliant swap surfaced as such, never silently dropped (no-fallbacks)
- [ ] Tests: gate filtering, cross-book ranking, "why now" delta detection

## Technical Approach
### Reuse
`fit.py` scorer, `swap.py` candidate ranking + FIT_GAIN_THRESHOLD, `persona_portfolio.py`
holdings link, portfolio exposure lookups, `SwapProposal` model.
### New
Book sweep iterator + per-client impact aggregator + ranker; "since last review" delta needs a
stored last-sweep marker (CIO-list version + DNA hash/timestamp per client).

## Dependencies
TASK-021 (swap engine) · TASK-022 (drift, for exposure helpers) · fit/DNA loaders

## Refs
backend/app/loaders/{fit,swap,tags}.py · backend/app/routers/ (portfolio routes) ·
docs/Requirements.md §UC-4, E12 · TASK-059 (the *other*, event-driven radar — keep separate)

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **`book.py` router (TASK-024) — the closest prior art and primary template.** `GET /book`
  already does ~80% of the data plumbing this task needs: a single-query, no-N+1 aggregation of
  per-client value-weighted `portfolio_fit`, `conflict_positions`, `total_positions`, plus a
  second query that joins `SwapProposal → Position → CIORecommendation` to produce ranked
  `top_swaps` (from_security → to_security, fit_gain, dna_reason) and a `kept_count` for
  conflicts with no real candidate. This is the aggregation to extend/clone, not rebuild.
- **`swap.py` (TASK-021).** `compute_swaps` already **applies the ≥10pp gate at write time**
  (`fit_gain <= FIT_GAIN_THRESHOLD` is filtered out, line 149), so every stored `SwapProposal`
  with `candidate_isin != NULL` and `fit_gain != NULL` has **already cleared the gate**. The
  radar does not re-run the engine — it reads `swap_proposals`. Conflicts with no compliant
  candidate are persisted as keep-reason rows (`candidate_isin=NULL`, `dna_reason=keep_reason`)
  — these are exactly the "conflicts but no swap" set AC-6 requires.
- **`fit.py` (TASK-020).** `_score_holding` (pure) and per-holding `fit_score` already stored on
  `enriched_holdings`; `portfolio_fit` is value-weighted at read time (book.py lines 75-89). The
  current→projected fit pair can be computed from these without new scoring.
- **`change_radar.py` + `radar.py` (TASK-059) — the *pattern* template, not shared logic.**
  Reuse the **shape**: book-wide sweep iterator, Pydantic `RadarResponse`/`RadarEvent`/router
  layout, `impacted_clients` JSONB breakdown, and the **no-fallbacks `unresolved`/`unresolved_reason`
  split** for surfacing-not-dropping. Do **NOT** reuse its scorer (`score_event`, exposure ×
  magnitude × recency) or its `ChangeEvent` table — TASK-062/TASK-063 mandate a distinct DNA/fit
  ranking with no shared scorer.
- **`persona_portfolio.py` (TASK-056).** Confirms each client's holdings are real `Position` rows
  with `current_chf` — so `exposure_chf_in_slot` resolves directly to `Position.current_chf`
  (each `SwapProposal.holding_id` IS a `Position.id`; one swap ↔ one slot). No sector/instrument
  fan-out needed (simpler than change_radar's `_client_exposure`).
- **Models:** `SwapProposal` (holding_id, candidate_isin/valor, fit_gain, cio_view, dna_reason,
  sources), `Position` (current_chf, sub_asset_class, industry_group, isin), `CIORecommendation`
  (cio_view, is_swap_candidate), `ClientDNA.version` (Integer, default 1) — the **only existing
  version/delta signal in the schema**.

### Dependencies Required
- Frontend packages: none (backend-only task).
- Backend packages: none new — `fastapi`, `sqlalchemy`, `pydantic` already in use.
- Database migrations: applied through `0011_change_events.py`. **Next free number is `0012`.**
  A migration is needed **only for "why now"** (see Database Impact) — the core ranking needs none.
- Docker services: Postgres (existing). No Redis/MinIO/LLM dependency (deterministic, no LLM —
  grounding rule G2 satisfied by construction since all numbers come from stored rows).

### Impact Assessment
#### Files to Modify / Create
- **NEW** `backend/app/loaders/improvement_radar.py`: the book sweep iterator + per-client impact
  aggregator + ranker + "why now" delta logic. Pure helpers (impact = Σ fit_gain × exposure,
  ranking, tiebreak) split out for unit-testing à la `change_radar.py`.
- **MODIFY** `backend/app/routers/book.py` (or **NEW** `backend/app/routers/improvements.py`):
  add `GET /book/improvements`. Recommendation: add to `book.py` — it already owns the `/book`
  prefix and the swap/exposure aggregation queries, keeping one place for book-wide reads.
- **MODIFY** `backend/app/routers/admin.py`: if "why now" needs a stored marker, add a
  `POST /admin/seed/improvement-marker` (or fold the marker write into the existing sweep) so the
  baseline is captured per sweep. Mirror the `seed_swap`/`seed_radar` try/except → HTTPException
  pattern (409 on RuntimeError, 500 otherwise).
- **MODIFY** `backend/app/main.py`: only if a new router file is created (`include_router`).
- **NEW** `backend/tests/test_improvement_radar.py`: gate filtering, cross-book ranking, why-now
  delta — mock-session pattern from `tests/test_change_radar.py`.

#### Components Affected
- `book.py` router: **MEDIUM** — additive endpoint; existing `GET /book` untouched.
- `swap.py` / `fit.py`: **LOW** — read-only consumers; no signature changes.
- Frontend (TASK-065 Before/After widget): **LOW/contract-only** — this task defines the
  `GET /book/improvements` response shape the widget will later consume.

#### API Changes
- **NEW** `GET /book/improvements?limit=N` → `{ clients: [...], no_swap_available: [...], total }`.
  Per client (ranked): `client_id`, `client_name`, `mandate`, `portfolio_fit` (current →
  projected), `resolvable_conflicts` (count), `improvable_chf` (Σ exposure in swappable slots),
  `impact` (Σ fit_gain × exposure_chf_in_slot), `why_now` (string/struct), `top_swaps`
  [{from, to, dna_reason, candidate_cio_view, fit_gain}]. `no_swap_available` carries clients
  with conflicts but zero compliant swaps (AC-6, no-fallbacks) — never silently dropped.

#### Database Changes
- **Core ranking: no schema change** — it aggregates existing `swap_proposals` + `positions`.
- **"Why now" (the one new persistence need):** "since last review" requires a stored baseline.
  Two viable shapes (decide in implementation):
  1. **NEW table `sweep_state`** (migration 0012): last-sweep CIO-list fingerprint (hash of the
     CIO recommendation set, since `CIORecommendation` has **no version column**) + a per-client
     `{client_id → dna_version, swept_at}` map. "Why now" = CIO fingerprint changed since last
     sweep, OR `ClientDNA.version` > stored version for that client.
  2. **Lighter, no-migration:** derive a weaker "why now" from existing timestamps
     (`ClientDNA.version`/`updated_at`, `CIORecommendation.updated_at`) with no persisted
     baseline — but then "since last review" is only "recently changed", not a true delta.
  → **Recommendation: option 1** (small `sweep_state` table). It's what makes the periodic
  "every 2–3 months" semantics real and is the honest read of AC-4.

### Implementation Checklist
- [ ] **Reuse `book.py`'s swap-aggregation query** instead of writing a new join — extend it with
      exposure-weighted impact and ranking.
- [ ] **Read stored `swap_proposals`; do NOT re-run `compute_swaps`** — the ≥10pp gate is already
      applied at write time (swap.py:149).
- [ ] Rank clients by `impact = Σ_slots(fit_gain × Position.current_chf)`; tiebreak by "why now".
- [ ] Keep ranking **fully separate from `change_radar.score_event`** — no shared scorer (AC, epic).
- [ ] Surface conflict-but-no-swap clients in a distinct list (no-fallbacks); never drop them.
- [ ] Every figure traceable to `SwapProposal.fit_gain` / `Position.current_chf` — model authors
      no numbers (grounding G2). No LLM call in this path.
- [ ] Add proper error handling (409/500) + structured logging mirroring `seed_swap`/`get_radar`.
- [ ] Tests: gate filtering, cross-book ranking, why-now delta detection.

### Risk Analysis
- **Risk Level:** MEDIUM (core is low; "why now" delta is the source of risk).
- **Main Risks:**
  - **"Why now" / "since last review" baseline** — no CIO-list version and no sweep marker exist
    today. *Mitigation:* add the minimal `sweep_state` table (migration 0012) with a CIO-set
    fingerprint + per-client DNA version; gate the migration behind this task so the core radar
    ships even if the delta logic is staged second.
  - **Ranking divergence from Change Radar** — accidental reuse of the exposure×magnitude×recency
    scorer would violate the "no shared scorer" rule. *Mitigation:* new pure scorer in
    `improvement_radar.py`; assert separation in tests.
  - **Exposure double-counting** — a position can carry multiple ranked `SwapProposal` rows (one
    per candidate). *Mitigation:* aggregate impact over the **best swap per slot/position**
    (max fit_gain), mirroring book.py's `swaps[:3]` per-position grouping and change_radar's
    best-per-(client,isin) dedup.
  - **Empty/unseeded book** — return gracefully (like `GET /book`), never 500 on no data.

### Estimated Effort
- Original: M.
- Adjusted: **M** (confirmed). Core ranking is S (reuses book.py aggregation); the "why now"
  marker table + delta detection is what holds it at M.
- Reason: most of the heavy lifting (gate, candidate filtering, exposure, fan-out shape) already
  exists in `swap.py` / `book.py` / `change_radar.py`; net-new is the ranking scorer, the response
  contract, and the sweep-state baseline.
