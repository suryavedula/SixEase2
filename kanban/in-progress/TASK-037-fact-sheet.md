# TASK-037: Fact-sheet assembler

**Status:** IN-PROGRESS · **Epic:** EPIC-09 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Deterministically assemble the message fact sheet: trigger, holding, proposal, numbers, mandate-impact-unchanged, DNA points with source ids, evidence. No LLM here.

## Acceptance Criteria
- [ ] fact sheet built from engine + DNA + news
- [ ] all numbers sourced, none invented
- [ ] includes source ids for provenance

## Dependencies
TASK-021, TASK-028

## Refs
Requirements §16 MSG2

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status
- **TASK-021** (swap engine) — IN-PROGRESS, **fully implemented**. `backend/app/loaders/swap.py`
  writes `swap_proposals` rows with `holding_id`, `candidate_isin`, `candidate_valor`,
  `dna_reason`, `cio_view`, `mandate_neutral=True`, `fit_gain`, `sources` JSONB. E8 invariant
  (mandate_neutral) is already set on every proposal.
- **TASK-028** (news match) — IN-PROGRESS, **fully implemented**. `backend/app/loaders/news_match.py`
  writes `news_items` rows with `headline`, `url`, `impact`, `matched_holdings`, `matched_themes`,
  `client_ids` (JSONB array of UUID strings). GIN index on `client_ids` makes per-client lookup fast.
- Both dependencies are **materially satisfied** — proceeding.

### Existing Resources Found
- **`MessageDraft` ORM model** (`backend/app/models/derived.py:116`) — already in schema
  from migration 0001. Columns: `client_id` (FK→clients), `fact_sheet` (JSONB — the MSG2
  locked fact payload), `draft_text`, `style`, `facts_used`, `provenance`, `status` (`DraftStatus`
  enum: `draft / approved / sent`). **No migration needed.**
- **`ClientDNA.exclusions` / `.tilts` JSONB** — each list item is a dict containing `text`,
  `tag`, `source_note_ids: [str(uuid)]` (Interaction UUIDs stored inline by the DNA loader
  at `dna.py:159`). Source note IDs are already resolved — no need to query `citations`.
- **`Alert` model** (`derived.py:173`) — `trigger`, `client_id`, `alert_class`, `evidence`
  (JSONB). For `dna_conflict` class alerts, `evidence[0]` contains `{isin, valor, issuer,
  security, current_chf, conflicts}` (set by `loaders/alerts.py:_generate_dna_conflict_alerts`).
- **`SwapProposal` model** (`derived.py:137`) — `holding_id` → Position FK, `candidate_isin`,
  `candidate_valor`, `dna_reason`, `cio_view`, `mandate_neutral`, `fit_gain`, `sources`.
  Indexed by `ix_swap_holding (holding_id)`.
- **`CIORecommendation`** (`source.py:105`) — joinable on `isin` to get `issuer`, `security`
  for the proposal candidate (display names not stored on SwapProposal itself).
- **`NewsItem`** (`derived.py:91`) — `headline`, `url`, `impact`, `published_at`, `sentiment`,
  `client_ids` (JSONB GIN-indexed). Filter: `client_ids @> [str(client_id)]`.
- **`total_chf` pattern** — already established in `loaders/drift.py:112`:
  `sum(float(p.current_chf) for p in positions)`. Reuse directly; do NOT query a separate
  aggregate table.
- **Admin router pattern** — additive endpoint + module docstring update, same as every prior
  loader task. Wire `POST /admin/assemble/fact-sheet`.

### Fact Sheet Structure (MSG2)

```python
{
    # All fields locked deterministically — no LLM authors any value.
    "trigger": alert.trigger,                     # string from Alert.trigger
    "holding": {
        "issuer":         position.issuer,
        "security":       position.security,
        "isin":           position.isin,
        "valor":          position.valor,
        "sub_asset_class": position.sub_asset_class,
        "industry_group":  position.industry_group,
        "current_chf":    float(position.current_chf),
        "target_chf":     float(position.target_chf),
    },
    "proposal": {                                 # best swap candidate (highest fit_gain)
        "candidate_isin":     proposal.candidate_isin,
        "candidate_valor":    proposal.candidate_valor,
        "candidate_issuer":   cio.issuer,         # joined from CIORecommendation on isin
        "candidate_security": cio.security,
        "dna_reason":         proposal.dna_reason,
        "cio_view":           proposal.cio_view,
        "fit_gain":           proposal.fit_gain,
        "mandate_neutral":    True,               # E8 invariant — always true
    },
    "numbers": {
        "current_chf":    float(position.current_chf),
        "target_chf":     float(position.target_chf),
        "fit_score":      float(enriched.fit_score),
        "portfolio_pct":  round(current_chf / total_portfolio_chf * 100, 2),
    },
    "mandate_impact_unchanged": True,             # E8 — spec invariant, always True
    "dna_points": [                               # relevant exclusions + tilts with source IDs
        {
            "value":          item["text"],
            "tag":            item.get("tag"),
            "source_note_id": item["source_note_ids"][0],  # first cited Interaction UUID
        }
        for item in (dna.exclusions or []) + (dna.tilts or [])
        if item.get("tag") and item.get("source_note_ids")
        and item["tag"] in conflict_tags         # only points relevant to this conflict
    ],
    "evidence": [                                 # up to 3 matched news items
        {
            "headline":           news.headline,
            "url":                news.url,
            "impact":             news.impact,
            "published_at":       str(news.published_at),
            "source_news_item_id": str(news.id), # provenance pointer
        }
        for news in relevant_news[:3]
    ],
}
```

**`proposal` is nullable** — if no swap candidate was found (E11 path), `proposal=None`.
The fact sheet is still valid; MSG3 will generate a "keep + monitor" message instead of a
swap recommendation.

### Algorithm (assemble_fact_sheet)

```
1. Load ClientDNA for client_id → raise RuntimeError if missing ("run seed/dna first")
2. Resolve alert:
     if alert_id provided → load Alert by id (must belong to client_id)
     else → SELECT Alert WHERE client_id=? AND alert_class='dna_conflict'
             AND status='open' ORDER BY severity DESC, created_at DESC LIMIT 1
3. Extract conflict isin from alert.evidence[0]["isin"]
4. Load Position: WHERE client_id=? AND isin=? → raise RuntimeError if missing
5. Load EnrichedHolding: JOIN on position.id → fit_score, conflicts JSONB
6. conflict_tags = {b["tag"] for b in enriched.conflicts if b.get("impact")=="exclusion"}
7. Load best SwapProposal:
     WHERE holding_id=position.id AND candidate_isin IS NOT NULL
     ORDER BY fit_gain DESC LIMIT 1
   If none → proposal_block = None
   If found → JOIN CIORecommendation ON isin=candidate_isin for display names
8. Compute total_portfolio_chf: SELECT sum(current_chf) WHERE client_id=?
9. Load relevant NewsItem: WHERE client_ids @> [str(client_id)]
     AND impact IN ('threat','opportunity') ORDER BY published_at DESC LIMIT 3
10. Assemble dna_points from DNA exclusions + tilts whose tag ∈ conflict_tags
11. Build fact_sheet dict (see structure above)
12. Create MessageDraft(client_id=client_id, fact_sheet=fact_sheet,
                        style=str(dna.style_profile) if dna.style_profile else None,
                        status=DraftStatus.DRAFT)
13. session.add(draft); await session.commit()
14. Return {"draft_id": str(draft.id), "client_id": str(client_id),
             "fact_sheet": fact_sheet, "has_proposal": proposal_block is not None}
```

### Dependencies Required
- **Frontend packages:** none (backend-only)
- **Backend packages:** none new — SQLAlchemy, asyncpg already present
- **Database migrations:** none — `message_drafts` table with `fact_sheet JSONB` exists
  in migration 0001 (`0001_initial_schema.py:160`)
- **Docker services:** `postgres` (must be running)
- **Seeding order:** `seed/portfolio → seed/crm → seed/dna → seed/tags → seed/fit →
  seed/swap → (scan/news optional) → assemble/fact-sheet`

### Impact Assessment

#### Files to Create
- `backend/app/loaders/fact_sheet.py` — `assemble_fact_sheet(session, client_id, alert_id=None)`

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/assemble/fact-sheet` + update module docstring
  with TASK-037

#### Components Affected
- `message_drafts` table: **HIGH (first write)** — TASK-037 is the sole writer of `fact_sheet`
  rows; table was empty before.
- TASK-038 (message render / MSG3 LLM): **HIGH dependency** — reads `MessageDraft.fact_sheet`
  to generate the prose draft. TASK-037 must complete before TASK-038 can run.
- Frontend message widget (TASK-040): **MEDIUM** — will consume the `MessageDraft` via a
  to-be-created router endpoint.
- `Alert` table: **READ-ONLY** — TASK-037 reads `Alert.trigger` + `Alert.evidence` to anchor
  the fact sheet; does NOT write or update alerts.
- `SwapProposal` table: **READ-ONLY** — selects best candidate; does NOT modify proposals.
- `NewsItem` table: **READ-ONLY** — selects relevant items; does NOT modify news rows.

#### API Changes
- **New:** `POST /admin/assemble/fact-sheet?client_id=<uuid>[&alert_id=<uuid>]`
  → `{"draft_id": str, "client_id": str, "fact_sheet": {…}, "has_proposal": bool}`
- No changes to existing endpoints.

#### Database Changes
- First data written to `message_drafts` (`fact_sheet` + `status=draft`). No schema change.

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Create `backend/app/loaders/fact_sheet.py` — pure async service, no FastAPI imports
- [ ] Alert resolution: prefer `dna_conflict` class; fall back to top-severity OPEN alert
- [ ] Position lookup: from `alert.evidence[0]["isin"]` via `Position WHERE client_id + isin`
- [ ] `dna_points` filter: only include DNA items whose `tag` ∈ `conflict_tags` (relevant, not all)
- [ ] `proposal=None` handled gracefully — fact sheet valid without swap candidate
- [ ] `evidence=[]` handled gracefully — no crash if scan/news hasn't run
- [ ] `total_portfolio_chf` via `func.sum(Position.current_chf)` — do NOT duplicate drift pattern
- [ ] CIO join for candidate display names — LEFT OUTER JOIN (candidate may not be in CIO table)
- [ ] `mandate_impact_unchanged=True` hardcoded (E8 — all proposals are same-sub_asset_class)
- [ ] `MessageDraft.style` = `str(dna.style_profile)` if available (feeds MSG3 / TASK-038)
- [ ] Add `POST /admin/assemble/fact-sheet` to `admin.py`; update module docstring
- [ ] Idempotent: calling twice creates two draft rows (idempotent is not the right word here —
      this is a new-draft-per-call operation, like a print job; not delete-and-reload)
- [ ] Smoke-test: `POST /admin/assemble/fact-sheet?client_id=<räber_uuid>` → 200 with
      draft_id; inspect `message_drafts` table for non-null `fact_sheet`
- [ ] Verify all numbers in fact_sheet trace to a table column (no invented values)
- [ ] Follow SOLID: `fact_sheet.py` has no FastAPI imports; single responsibility (assemble only)

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *No OPEN dna_conflict alert for a client:* degraded gracefully — fall back to top-severity
    alert of any class. If no alerts at all, return `{"status": "no_alerts"}` without creating
    a draft. Mitigation: add `RuntimeError("No open alerts — run seed/alerts first")`.
  - *alert.evidence[0] missing isin:* some alert classes store issuer name but not isin.
    Mitigation: check evidence for `isin`, fall back to `valor`, then issuer text search
    (`Position.issuer.ilike(f"%{issuer}%")`). For `dna_conflict` class this is not a risk —
    the alerts loader always writes `isin` in evidence.
  - *CIORecommendation not found for candidate_isin:* the CIO list may not include all swap
    candidates (e.g., seeded trigger articles). Mitigation: LEFT OUTER JOIN; set
    `candidate_issuer = None` gracefully. Not a blocking error.
  - *`dna_points` empty (DNA exclusions have no tag or no source_note_ids):* possible if
    `seed/dna` ran but LLM produced untagged attributes. Mitigation: `dna_points=[]` is
    valid in the spec — MSG3 will generate the message using trigger + numbers only.

### Estimated Effort
- Original: **S**
- Adjusted: **S** — all schema exists; all source data is queryable from existing tables;
  no LLM, no new migrations. ~6 DB queries + one insert per call. The main complexity is
  the alert→position→proposal→news resolution chain, but each step is a single SQL query.

---

## Implementation (2026-06-20)

**Files created**
- `backend/app/loaders/fact_sheet.py` — `assemble_fact_sheet(session, client_id, alert_id=None)`:
  6-query resolution chain (DNA → alert → position+enriched → swap proposal → portfolio total
  → news items) + `dna_points` filter by `conflict_tags`, `MessageDraft` insert, structured log.
  No LLM. `proposal=None` handled cleanly (E11 path). `evidence=[]` when no news matched.

**Files modified**
- `backend/app/routers/admin.py` — added `import uuid`, `from app.loaders.fact_sheet import
  assemble_fact_sheet`, `POST /admin/assemble/fact-sheet?client_id=<uuid>[&alert_id=<uuid>]`,
  and updated module docstring.
- Also applied pending migration `0009_alert_lifecycle.py` via `alembic upgrade head`
  (authored by TASK-035; just needed running).

**Verified live (seed/fit → seed/swap → upgrade head → seed/alerts → assemble/fact-sheet):**
- `POST /admin/seed/fit` → `{"clients_scored":7,"holdings_scored":141}` ✓
- `POST /admin/seed/swap` → `{"proposals_written":20}` ✓
- `POST /admin/seed/alerts` → `{"dna_conflict":20,...}` ✓
- `POST /admin/assemble/fact-sheet?client_id=<sample_growth>` → 200 with full MSG2 structure:
  `trigger`, `holding` (7 sub-fields), `proposal: null` (E11 path — all IT CIO BUYs share
  us-tech tag), `numbers` (current_chf=347911, portfolio_pct=1.58), `mandate_impact_unchanged:true`,
  `dna_points:[]` (synthetic DNA has empty source_note_ids — correct for seeded clients),
  `evidence:[]` (scan/news not run — correct degraded mode).
- `message_drafts` table: row written with all 7 MSG2 keys, `status=DRAFT` ✓
- 409 returned for client with no dna_conflict alert (Räber — clear message) ✓
- Two calls → two distinct draft_id rows in message_drafts (new-draft-per-call semantics) ✓
- `dna_points` will populate once real DNA is extracted (LLM proxy issue tracked separately)

Ready for `/review-task`.
