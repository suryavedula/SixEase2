# TASK-011: Synthetic client generator

**Status**: DONE · **Epic:** EPIC-02 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned**: Unassigned · **Started**: 2026-06-20 · **Analysis Completed**: 2026-06-20 · **Completed**: 2026-06-20

## Description
Generate ~100 reproducible, seeded synthetic clients grounded in the four archetypes (varied exclusions/tilts/mandates/styles) for the scale proof.

## Acceptance Criteria
- [x] ~100 clients with varied DNA, seeded
- [x] each assigned a mandate + sample portfolio
- [x] clearly labelled synthetic (G6)

## Dependencies
TASK-010, TASK-016

## Refs
Requirements §12 D4

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status

| Task | Status | Impact on TASK-011 |
|---|---|---|
| **TASK-010** (instrument tags) | IN-PROGRESS | `instrument_tags()` already in `app/tags.py` — available now |
| **TASK-016** (DNA extraction) | BACKLOG | Defines DNA schema, but TASK-011 writes **synthetic** DNA directly — no LLM extraction needed |

**Conclusion:** Both dependencies are resolvable now. `client_dna` table exists (migration 0001); `instrument_tags()` is already exported from `app/tags.py`. TASK-011 can proceed independently.

### Existing Resources Found

- **`clients` table** (`models/source.py:Client`) — synthetic rows go here. Name unique constraint (`uq_clients_name`, migration 0002) enforces idempotency via ON CONFLICT DO NOTHING.
- **`client_dna` table** (`models/derived.py:ClientDNA`) — synthetic DNA rows: `exclusions`, `tilts`, `values`, `style_profile`, `mandate`. Shape established in migration 0001.
- **`positions` table** (`models/source.py:Position`) — synthetic portfolios are copies of the 3 Sample mandate portfolios already loaded by TASK-008 (~70 positions each).
- **`enriched_holdings` table** (`models/derived.py:EnrichedHolding`) — to be created inline for new positions (avoids requiring seed_tags re-run).
- **`app/tags.py:instrument_tags()`** — already available; used to tag copied positions inline.
- **`loaders/crm.py:load_crm()`** — exact loader pattern to follow (async, single commit, idempotent).
- **`loaders/portfolio.py:load_portfolio()`** — pattern for position copying.
- **`routers/admin.py`** — endpoint pattern for `POST /admin/seed/synthetic`.
- **`app/logging.py:get_logger()`** — structured log output.
- **`app/db.py:get_session`** — session injection.
- **`Mandate` enum** (`DEFENSIVE`, `BALANCED`, `GROWTH`) — already defined in `models/enums.py`.

### Tag Vocabulary Available (from `app/tags.py`)

Exclusion tags: `us-tech`, `fossil`, `fossil-fuel`, `deforestation-risk`, `pharma`, `labour-risk`  
Tilt tags: `sustainability`, `neuro-research`, `luxury`, `tech`

### Portfolio Data Provenance

Synthetic clients do **not** get invented holdings. Their portfolios are copied **verbatim** from the three `Sample Defensive/Balanced/Growth` clients already loaded from the provided workbook (`SwissHacks Portfolio Construction.xlsx`). The data flow:

```
Workbook "Sample Portfolio Defensive"  ──clone──▶  [SYNTHETIC] Defensive Value #001–025
Workbook "Sample Portfolio Balanced"   ──clone──▶  [SYNTHETIC] Purpose ESG #001–025
                                       ──clone──▶  [SYNTHETIC] Personal Cause Health #001–025
Workbook "Sample Portfolio Growth"     ──clone──▶  [SYNTHETIC] Corporate Reputation #001–025
```

Instrument mix, weights, Valor/ISIN/MIC identifiers, and CHF values are **identical to the workbook**. The only differentiation between clients of the same archetype is their `client_dna` (exclusions, tilts, communication style).

The loader reads sample positions from the DB at runtime (`SELECT positions WHERE client.name = 'Sample {Mandate}'`) — no hardcoded positions. If the sample portfolio hasn't been loaded yet, the loader raises a clear error.

### Four Archetypes → Synthetic DNA Templates

| Archetype | Mandate | Base Exclusions | Base Tilts | Variation axes |
|---|---|---|---|---|
| Defensive Value (Räber-type) | DEFENSIVE | `us-tech` | `tech` (non-US) | ± add `fossil` exclusion |
| Purpose ESG (Huber-type) | BALANCED | `fossil`, `fossil-fuel`, `deforestation-risk` | `sustainability` | ± add `labour-risk` exclusion |
| Corporate Reputation (Ammann-type) | GROWTH | `labour-risk` | `luxury` | ± add `deforestation-risk` exclusion |
| Personal Cause / Health (Schneider-type) | BALANCED | `pharma` | `neuro-research` | ± add `sustainability` tilt |

Mandate distribution: 25 clients per archetype = 100 total (Defensive:25, Balanced:50, Growth:25).  
Seed: `random.seed(42)` — stdlib `random`, no new package needed.

### G6 Labelling

Client name format: `[SYNTHETIC] {ArchetypeName} #{n:03d}`  
Example: `"[SYNTHETIC] Purpose ESG #012"` — unambiguous in any query result.

### Dependencies Required

- **Frontend packages:** none (backend-only)
- **Backend packages:** none new — `sqlalchemy`, `asyncpg`, `random` (stdlib) already available
- **Database migrations:** none — `clients`, `positions`, `client_dna`, `enriched_holdings` all created in migration 0001
- **Docker services:** `postgres` (already up)
- **Data dependency:** `positions` for Sample Defensive/Balanced/Growth must exist (TASK-008 ✓)

### Impact Assessment

#### Files to Create
- `backend/app/loaders/synthetic.py` — `load_synthetic_clients(session) → dict[str, int]`

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/seed/synthetic` endpoint + docstring entry

#### Components Affected
- `clients` table: **HIGH (100 new rows)** — all synthetic, uniquely named, upserted by name
- `positions` table: **HIGH (~7,000 new rows)** — 100 clients × ~70 positions each (copied from sample portfolios)
- `client_dna` table: **HIGH (100 new rows)** — synthetic DNA per client
- `enriched_holdings` table: **HIGH (~7,000 new rows)** — tagged inline as positions are created
- TASK-020 (fit scorer): **HIGH dependency** — will run over synthetic clients' `client_dna` vs `enriched_holdings.tags`
- TASK-024 (book view): **HIGH dependency** — renders the 100-client ranked queue that D4 requires
- TASK-055 (seed personas end-to-end): **MEDIUM** — the four real personas are separate; synthetic clients complement them

#### API Changes
- New: `POST /admin/seed/synthetic` → `{"status": "ok", "loaded": {"clients": 100, "positions": N, "dna_rows": 100, "enriched_holdings": N}}`
- No changes to existing endpoints.

#### Database Changes
- No migration required.
- 100 rows inserted into `clients` (idempotent via ON CONFLICT (name) DO NOTHING).
- ~7,000 rows inserted into `positions` (deleted-and-reloaded per synthetic client, like CRM loader).
- 100 rows upserted into `client_dna` (one per client).
- ~7,000 rows upserted into `enriched_holdings` (on_conflict_do_update on position_id).

### Module Design

#### `backend/app/loaders/synthetic.py`

```python
SEED = 42
N_PER_ARCHETYPE = 25  # 4 × 25 = 100 total

ARCHETYPES = [
    {
        "label": "Defensive Value",
        "mandate": Mandate.DEFENSIVE,
        "base_exclusions": ["us-tech"],
        "base_tilts": ["tech"],
        "optional_exclusions": ["fossil"],  # 50% chance added
    },
    {
        "label": "Purpose ESG",
        "mandate": Mandate.BALANCED,
        "base_exclusions": ["fossil", "fossil-fuel", "deforestation-risk"],
        "base_tilts": ["sustainability"],
        "optional_exclusions": ["labour-risk"],
    },
    {
        "label": "Corporate Reputation",
        "mandate": Mandate.GROWTH,
        "base_exclusions": ["labour-risk"],
        "base_tilts": ["luxury"],
        "optional_exclusions": ["deforestation-risk"],
    },
    {
        "label": "Personal Cause Health",
        "mandate": Mandate.BALANCED,
        "base_exclusions": ["pharma"],
        "base_tilts": ["neuro-research"],
        "optional_tilts": ["sustainability"],  # 50% chance added
    },
]

STYLE_PROFILES = ["data-driven", "values-led", "relationship-first", "formal"]

async def load_synthetic_clients(session: AsyncSession) -> dict[str, int]:
    """
    1. rng = random.Random(SEED)
    2. Fetch sample positions per mandate (keyed by mandate).
    3. For each archetype × N_PER_ARCHETYPE:
       a. Build name "[SYNTHETIC] {label} #{i:03d}"
       b. Upsert Client (ON CONFLICT (name) DO NOTHING)
       c. Delete + re-insert positions copied from sample mandate portfolio
       d. Upsert enriched_holdings per position (tags via instrument_tags())
       e. Upsert ClientDNA with varied exclusions/tilts
    4. Single commit; return counts.
    """
```

Key decisions:
- Use `random.Random(SEED)` (instance, not global) — thread-safe and doesn't affect global state.
- Positions are copied with the new `client_id`; all field values replicate the sample template.
- `enriched_holdings` upserted inline so the synthetic book is immediately queryable without re-running seed_tags.
- `ClientDNA.exclusions` and `.tilts` are lists of `{"tag": "us-tech", "source": "synthetic", "confidence": 1.0}` items — matches the shape TASK-016 will produce for real clients, ensuring downstream compatibility.
- Style variation: each client gets a style drawn from STYLE_PROFILES using the seeded RNG.
- All other DNA fields (`life_events`, `promises`, `business_context`, etc.) are `None` for synthetic clients — TASK-055 fills them for the four real personas.

### Implementation Checklist
- [ ] Write `backend/app/loaders/synthetic.py` with `ARCHETYPES`, `SEED=42`, `load_synthetic_clients(session)`
- [ ] Fetch sample mandate positions from DB inside loader (don't hardcode — degrade gracefully if missing)
- [ ] Use `random.Random(SEED)` (instance, not module-level) for reproducibility
- [ ] Upsert `Client` with `ON CONFLICT (name) DO NOTHING`; skip if already exists
- [ ] Copy positions (delete-and-reload per client); create `enriched_holdings` inline using `instrument_tags()`
- [ ] Upsert `ClientDNA` keyed on `client_id` (unique constraint already exists)
- [ ] DNA `exclusions`/`tilts` items shaped as `{"tag": str, "source": "synthetic", "confidence": 1.0}` for TASK-016/020 compatibility
- [ ] Add `POST /admin/seed/synthetic` to `admin.py`; follow the existing endpoint pattern exactly
- [ ] Idempotency test: call twice, assert counts unchanged
- [ ] Smoke-test: call endpoint, verify `SELECT COUNT(*) FROM clients WHERE name LIKE '[SYNTHETIC]%'` = 100
- [ ] Verify G6: query `SELECT name FROM clients LIMIT 5` — all synthetic names must be prefixed `[SYNTHETIC]`
- [ ] Follow SOLID; no comments explaining what the code does
- [ ] Reuse `instrument_tags()` from `app/tags.py` — no duplicate tag logic

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *Sample portfolios not loaded when seed_synthetic runs* — loader queries Sample clients; if missing, raises `RuntimeError("Run /admin/seed/portfolio first")`. Mitigation: same guard pattern as `load_tags`.
  - *`uq_clients_name` constraint conflicts on re-run* — use `ON CONFLICT (name) DO NOTHING` for client upsert; skip position/DNA reload if client already had its rows. Mitigation: detect existing client by name before doing position delete-reload (same as `load_crm` pattern).
  - *7,000 position inserts slow on first run* — single `session.add_all()` call per client batches inserts; all 100 clients in one transaction. Mitigation: acceptable for a one-time seed operation; add timing log.
  - *ClientDNA shape incompatibility with TASK-016* — synthetic DNA uses `{"tag": str, "source": "synthetic"}` items; TASK-016 must produce the same schema. Mitigation: verify shape when TASK-016 is implemented; adjust if needed.

### Estimated Effort
- Original: **M**
- Adjusted: **S** — all tables exist, tag vocabulary ready, loader/endpoint patterns established. Main work is authoring the `ARCHETYPES` map and the copy-position loop.
