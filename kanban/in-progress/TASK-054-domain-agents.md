# TASK-054: Domain-agent wiring

**Status:** IN-PROGRESS · **Epic:** EPIC-13 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Wire CRM/Portfolio/News/Message agents to their engines (DNA builder, personalization, watchlist monitor, message generator) behind the orchestrator.

## Acceptance Criteria
- [ ] four domain agents callable via orchestrator
- [ ] each delegates to its engine
- [ ] consistent tool/result contracts

## Dependencies
TASK-016, TASK-021, TASK-028, TASK-038, TASK-053

## Refs
Requirements §20 ST5

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status

| Task | Status | What it provides |
|---|---|---|
| TASK-016 (DNA extract) | IN-PROGRESS — `backend/app/loaders/dna.py` fully implemented | `extract_dna(session, client_id?)` → structured ClientDNA rows + citations |
| TASK-021 (swap engine) | IN-PROGRESS — `backend/app/loaders/swap.py` fully implemented | `compute_swaps(session, client_id?)` → SwapProposal rows with fit_gain + dna_reason |
| TASK-028 (news match) | IN-PROGRESS — `backend/app/loaders/news_match.py` fully implemented | `scan_news_for_client(session, client_id)` → NewsItem rows matched to watchlist |
| TASK-038 (message render) | IN-PROGRESS — `backend/app/loaders/message_render.py` fully implemented | `render_message_draft(session, draft_id, preset?)` → styled draft text + guardrail |
| TASK-053 (LangGraph) | **BACKLOG — NOT STARTED** | LangGraph router + `StateGraph` wiring; `langgraph` not in `requirements.txt` |

**Key finding**: TASK-053 is the immediate blocker for the "callable via orchestrator" acceptance criterion. However, TASK-054 can fully define the four domain agent wrappers with a consistent protocol contract so TASK-053 can plug them in without rework. No LangGraph code should be written here — that ownership belongs to TASK-053.

### Existing Resources Found

- **`backend/app/loaders/dna.py`** — `extract_dna(session, client_id?)` and `apply_dna_delta(session, client_id, delta, source_interaction_id)`. Returns `{client_name: 1}` dict. Idempotent upsert to `client_dna`.
- **`backend/app/loaders/style_profile.py`** — style-profile extraction; populated into `ClientDNA.style_profile`. Called after DNA seed.
- **`backend/app/loaders/swap.py`** — `compute_swaps(session, client_id?)`. Returns `{clients_processed, proposals_written}`. Requires prior fit scoring (seed/fit must run first).
- **`backend/app/loaders/news_match.py`** — `scan_news_for_client(session, client_id)` and `scan_news_all_clients(session)`. Fetches live articles from Event Registry, matches against watchlist, LLM-classifies impact, persists NewsItem rows.
- **`backend/app/loaders/message_render.py`** — `render_message_draft(session, draft_id, preset_override?)`. Takes a MessageDraft with a populated `fact_sheet`, renders to prose, validates with MSG4 guardrail.
- **`backend/app/loaders/watchlist.py`** — `build_watchlists(session, client_id?)`. Derives held-entity + DNA-theme keyword union per client. News agent depends on watchlists being built first.
- **`backend/app/llm.py`** — `json_chat(messages, schema, ...)` with tenacity retries; singleton pattern via `get_client()`. Already in use by all four engines.
- **`backend/app/db.py`** — `get_session` async dependency. Use exactly as-is.
- **`backend/app/logging.py`** — `get_logger(__name__)`. All agents must log with structured fields.
- **`backend/app/models/derived.py`** — `ClientDNA`, `SwapProposal`, `NewsItem`, `MessageDraft` all exist with correct schema.

### What Does NOT Exist

- `backend/app/agents/` directory — does not exist; must be created
- No `langgraph` in `requirements.txt` (comment says it is added by TASK-053)
- No `AgentRequest`/`AgentResult` shared protocol — must be defined here
- No LangGraph `StateGraph` — belongs in TASK-053

### Dependencies Required

- **Backend packages**: No new packages. All four engines already use `sqlalchemy`, `pydantic`, `openai`, `tenacity` which are present in `requirements.txt`. LangGraph belongs to TASK-053.
- **Database migrations**: None. All tables exist (`client_dna`, `swap_proposals`, `news_items`, `message_drafts`, `client_watchlists`).
- **Docker services**: All required — `postgres`, `redis`, `ollama`/Phoeniqs, `minio`. Running via existing `docker-compose.yml`.

### Impact Assessment

#### Files to Create
- `backend/app/agents/__init__.py` — barrel export of the four agent callables
- `backend/app/agents/base.py` — shared `AgentRequest`, `AgentResult` Pydantic models (the contract TASK-053 will call)
- `backend/app/agents/crm_agent.py` — wraps `extract_dna()`; CRM Agent → DNA Builder
- `backend/app/agents/portfolio_agent.py` — wraps `compute_swaps()`; Portfolio Agent → Personalization Engine
- `backend/app/agents/news_agent.py` — wraps `scan_news_for_client()`; News Agent → Watchlist Monitor
- `backend/app/agents/message_agent.py` — wraps `render_message_draft()`; Message Agent → Message Generator

#### Files to Modify
- None (no new routers, no migration, no `main.py` change needed — TASK-053 will import from `app.agents`)

#### Components Affected
- `backend/app/loaders/dna.py`: LOW — read-only import; no changes needed
- `backend/app/loaders/swap.py`: LOW — read-only import; no changes needed
- `backend/app/loaders/news_match.py`: LOW — read-only import; no changes needed
- `backend/app/loaders/message_render.py`: LOW — read-only import; no changes needed

#### API Changes
- None. TASK-054 introduces no new HTTP endpoints. The agents are internal callables that TASK-053's LangGraph router will dispatch.

#### Database Changes
- None. All derived tables already exist.

### Agent Protocol Contract

The shared contract that makes all four agents callable uniformly by the orchestrator:

```python
# backend/app/agents/base.py
import uuid
from typing import Any
from pydantic import BaseModel

class AgentRequest(BaseModel):
    client_id: uuid.UUID
    params: dict[str, Any] = {}   # agent-specific extras (e.g. draft_id, preset)

class AgentResult(BaseModel):
    agent: str                     # "crm" | "portfolio" | "news" | "message"
    client_id: uuid.UUID
    status: str                    # "ok" | "error"
    payload: dict[str, Any]        # engine-specific output (counts, draft_id, etc.)
    error: str | None = None
```

Each domain agent exposes a single async function:
```python
async def invoke(request: AgentRequest, session: AsyncSession) -> AgentResult: ...
```

This is the contract TASK-053 registers as a LangGraph node.

### Engine → Agent Mapping

| Domain Agent | Engine Function | Input extras (params) | Output payload fields |
|---|---|---|---|
| CRM Agent (`crm`) | `extract_dna(session, client_id)` | none | `{extracted: {client_name: 1}, dna_id: str}` |
| Portfolio Agent (`portfolio`) | `compute_swaps(session, client_id)` | none | `{clients_processed, proposals_written}` |
| News Agent (`news`) | `scan_news_for_client(session, client_id)` | none | `{matched, classified, inserted}` |
| Message Agent (`message`) | `render_message_draft(session, draft_id, preset?)` | `draft_id: UUID`, `preset?: str` | `{draft_id, preset, draft_text, guardrail_passed}` |

### Implementation Checklist
- [ ] Create `backend/app/agents/base.py` with `AgentRequest`, `AgentResult` Pydantic models
- [ ] Create `backend/app/agents/crm_agent.py` — `invoke()` wraps `extract_dna()`; reads back `ClientDNA.id` for payload
- [ ] Create `backend/app/agents/portfolio_agent.py` — `invoke()` wraps `compute_swaps()`; propagates error for missing DNA/fit
- [ ] Create `backend/app/agents/news_agent.py` — `invoke()` wraps `scan_news_for_client()`; propagates RuntimeError for missing watchlist
- [ ] Create `backend/app/agents/message_agent.py` — `invoke()` requires `params.draft_id`; wraps `render_message_draft()`
- [ ] Create `backend/app/agents/__init__.py` — barrel exports: `crm_agent`, `portfolio_agent`, `news_agent`, `message_agent`
- [ ] All agents use `get_logger(__name__)` and emit structured log on entry + exit
- [ ] All agents catch exceptions and return `AgentResult(status="error", error=str(exc))` — never propagate to caller
- [ ] Write `backend/tests/test_domain_agents.py` — unit tests mocking the engine functions
- [ ] Confirm TASK-053 (LangGraph) is unblocked by having the `invoke()` interface ready

### Risk Analysis
- **Risk Level**: MEDIUM
- **Main Risks**:
  - **TASK-053 still in BACKLOG**: The "callable via orchestrator" AC cannot be verified until TASK-053 is started. Mitigation: define the `AgentRequest`/`AgentResult` contract and `invoke()` interface here — TASK-053 can import and wire without rework. Agent unit tests run without LangGraph.
  - **Message agent requires `draft_id`**: Unlike the other three agents, the message agent needs an existing `MessageDraft` row (with a populated `fact_sheet`). The orchestrator must know the `draft_id` before calling the message agent — this is a state dependency TASK-053's `StateGraph` must handle. Mitigation: document this in the `message_agent.py` module; `params.draft_id` is required and validated at entry.
  - **News agent watchlist precondition**: `scan_news_for_client()` raises `RuntimeError` if no watchlist has been built. The agent must catch this and return `status="error"` with a clear message. Mitigation: handled in the `invoke()` wrapper.
  - **Engine functions are not idempotent on first-run**: DNA and swap engines require prior seeding steps (`seed/crm`, `seed/portfolio`, etc.). The agents wrap the same precondition checks the engines already have.

### Estimated Effort
- Original: M
- Adjusted: S
- Reason: All four engines are fully implemented. This task is pure wrapping — thin adapter functions with a shared protocol. No new LLM logic, no schema changes, no new packages. TASK-053 (LangGraph) is the bigger task; TASK-054 is its pre-condition.
