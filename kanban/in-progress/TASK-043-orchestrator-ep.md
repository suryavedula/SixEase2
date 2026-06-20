# TASK-043: Orchestrator endpoint (request to view spec)

**Status:** IN-PROGRESS · **Epic:** EPIC-10 · **Priority:** P0 · **Type:** feature · **Effort:** L · **Created:** 2026-06-20
**Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Backend endpoint that turns a command/NL request into a validated view spec via tool-as-component: the LLM selects widgets and supplies parameters; data tools fetch real values into props. Streams or returns the spec.

## Acceptance Criteria
- [ ] request resolves to entity + view variant
- [ ] props are fetched by tools, not authored by the LLM (grounding)
- [ ] returns a spec the registry can render

## Dependencies
TASK-012, TASK-018, TASK-026, TASK-041

## Refs
Requirements §18 (tool-as-component), §17 UI-2

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status

| Task | Status | What it provides |
|---|---|---|
| TASK-012 (LLM abstraction) | IN-PROGRESS — `backend/app/llm.py` fully implemented | `chat()`, `json_chat()` with tenacity retries + fence-stripping; `get_client()` singleton |
| TASK-018 (DNA API) | IN-PROGRESS — `backend/app/routers/dna.py` fully implemented | `GET /clients/{id}/dna` with hydrated sources; `ClientDNA` ORM populated |
| TASK-026 (Holdings enrichment) | IN-PROGRESS — verified live | `GET /clients/{id}/portfolio/live`, `/fit`, `/allocation`, `/swaps` all working |
| TASK-041 (Component registry) | IN-PROGRESS — **code not yet written** | `frontend/src/registry/` does not exist; `WidgetSpec` type not defined yet |

**Verdict:** TASK-012, 018, 026 are materially satisfied (code implemented). TASK-041 is the only real missing piece — but TASK-043 is a **backend** endpoint that *defines* the `WidgetSpec` wire format; TASK-041 is its frontend consumer. Proceeding: the spec contract established here becomes the API TASK-041 must satisfy.

### Existing Resources Found

- **`backend/app/llm.py`** — `json_chat(messages, schema, ...)` accepts a Pydantic schema and retries up to 3×. This is the NL classification engine for TASK-043.
- **`backend/app/db.py`** — `get_session` async dependency; reuse exactly.
- **`backend/app/models/source.py:Client`** — `id (UUID)`, `name (Text)`, `mandate (Mandate enum)`. Client name resolution uses `Client.name.ilike(f"%{name}%")`.
- **`backend/app/routers/*.py`** — all domain endpoints exist and return grounded data; widgets call them directly. Orchestrator only needs to produce `{ component, props }` — props are routing params (`clientId`), not data values.
- **`frontend/src/components/widgets/index.ts`** — 11 widgets barrel-exported: `AllocationDonut`, `BookList`, `ConflictsList`, `DnaCard`, `DnaRadar`, `DriftBars`, `FitHeatmap`, `HoldingsTable`, `MessageDraftPanel`, `RelationshipTimeline`, `SectorTreemap`, `SwapBeforeAfter`. All accept `{ clientId: string }` (BookList takes no props). These are the valid `component` values.
- **`frontend/src/components/shell/InputDock.tsx`** — `submit()` is currently a no-op. TASK-042 will wire it to `POST /orchestrate`.
- **`frontend/src/api/client.ts`** — `apiPost<T>()` is the frontend call helper TASK-042 will use to call this endpoint.
- **TASK-042 stub contract** — already specifies the wire format: `POST /orchestrate` · request: `{ query: string; scope: string }` · response: `{ specs: WidgetSpec[] }`. TASK-043 must match this exactly.

### WidgetSpec Wire Contract

```typescript
// Agreed contract between backend (TASK-043) and frontend (TASK-041 / TASK-042)
type WidgetSpec = { component: string; props: Record<string, unknown> }

// POST /orchestrate
// Request
{ query: string; scope?: "all"|"clients"|"market"|"documents"|"analysis"; client_id?: string }

// Response
{
  specs: WidgetSpec[];
  resolved_client_id?: string;  // UUID string, so frontend can lift clientId state
  entity?: string;              // e.g. "ClientDNA + PortfolioView"
  view_variant?: string;        // e.g. "overview"
}
```

### Grounding Rule (UI-2 / §18)

The LLM is allowed to:
- Classify intent (action + client name hint)
- Select which widget components to include

The LLM must NOT:
- Author any numbers, prices, or portfolio data
- Generate client IDs (must be resolved from DB)
- Produce widget props other than routing params (`clientId`)

All real data fetching happens inside the widgets themselves when they render (they call the existing `/portfolio/fit`, `/dna`, etc. endpoints). The orchestrator's job is to produce a routing spec only.

### View Catalogue — Action → Widget Mapping

| Action | Widgets in spec | Entity | View Variant |
|---|---|---|---|
| `/client <name>` | DnaCard · HoldingsTable · RelationshipTimeline | ClientDNA + PortfolioView | overview |
| `/portfolio <name>` | AllocationDonut · DriftBars · HoldingsTable · FitHeatmap | PortfolioView | allocation_drift |
| `/dna <name>` | DnaCard · DnaRadar · RelationshipTimeline | ClientDNA | card_radar |
| `/swaps <name>` | SwapBeforeAfter · ConflictsList | SwapProposal | before_after |
| `/message <name>` | MessageDraftPanel | MessageDraft | draft |
| `/book` | BookList | Book | list |
| NL → LLM classifies → above | same as above | — | — |
| unknown / error | FallbackCard | — | — |

### Implementation Plan

#### Files to Create
- `backend/app/routers/orchestrator.py` — `POST /orchestrate`; slash-command fast-path + NL LLM path; client name resolution; spec assembly; Pydantic `WidgetSpec` + `OrchestrateRequest` + `OrchestrateResponse`

#### Files to Modify
- `backend/app/main.py` — `from app.routers import orchestrator` + `app.include_router(orchestrator.router)` (one import, one line)

#### No database migrations required
No new schema. Client name lookup uses the existing `clients` table.

#### No new Python packages required
`openai`, `tenacity`, `pydantic`, `sqlalchemy`, `fastapi` all present in `requirements.txt`.

### Implementation Checklist
- [ ] Create `backend/app/routers/orchestrator.py`
  - [ ] `WidgetSpec(component, props)` Pydantic model — this IS the protocol contract
  - [ ] `OrchestrateRequest(query, scope, client_id?)` request model
  - [ ] `OrchestrateResponse(specs, resolved_client_id?, entity?, view_variant?)` response model
  - [ ] `_parse_slash()` — regex fast-path; maps `/client`, `/portfolio`, `/dna`, `/swaps`, `/message`, `/book` to action + arg; no LLM call
  - [ ] `_Intent` Pydantic schema for LLM output (action, client_name)
  - [ ] NL path: `json_chat(messages, _Intent)` to classify; system prompt lists 6 valid actions
  - [ ] `_resolve_client(name, session)` — `Client.name.ilike(f"%{name}%")`; returns first match
  - [ ] Spec builder functions: `_client_specs`, `_portfolio_specs`, `_dna_specs`, `_swaps_specs`, `_message_specs`, `_book_specs`, `_fallback`
  - [ ] `POST /orchestrate` handler: slash → LLM → resolve client → assemble specs
  - [ ] All user-facing strings (fallback messages) in Portuguese (per CLAUDE.md)
  - [ ] Structured logging on request + resolution
  - [ ] Graceful degradation: LLM failure → FallbackCard (never 500)
- [ ] Register in `backend/app/main.py`
- [ ] Manual smoke-test: `POST /orchestrate {"query": "/client Schneider"}` → 3 specs with real client UUID

### Risk Analysis
- **Risk Level:** LOW–MEDIUM
- **Main Risks:**
  - **TASK-041 not done**: `FallbackCard` doesn't exist in the frontend yet. Mitigation: the registry validates component names — unknown names fall through gracefully. TASK-043 defines the contract; TASK-041 implements the consumer.
  - **LLM unavailable at test time**: The NL path requires Ollama/Phoeniqs to be running. Mitigation: slash-command fast-path requires no LLM — all demo commands can use `/client Schneider` style. LLM failure returns `FallbackCard` not a 500.
  - **Client name ambiguity**: "Huber" substring-matches "Huber" uniquely in the 4-persona set. With synthetic clients seeded, ILIKE could match multiple. Mitigation: `.scalars().first()` returns the first match; for the hackathon demo the 4 real personas have unique surnames.
  - **Streaming scope**: Task description says "streams or returns the spec." For the hackathon, returning the full spec as JSON is sufficient; SSE streaming is a V2 enhancement. AC#3 only requires "returns a spec the registry can render."

### Estimated Effort
- Original: L
- Adjusted: S–M
- Reason: All plumbing exists (LLM client, DB session, router patterns). The orchestrator is ~100 lines of routing logic with no new schema, no migration, no new packages. The "L" estimate assumed building the LLM tool-calling loop from scratch — the simpler LLM-as-classifier approach satisfies all ACs without that complexity.
