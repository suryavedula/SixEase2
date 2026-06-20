# TASK-053: LangGraph orchestrator and routing

**Status:** IN-PROGRESS · **Epic:** EPIC-13 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Set up the LangGraph orchestrator that routes RM requests/events to domain agents; keep trust-critical flows deterministic (pipelines), not free-form agent chatter.

## Acceptance Criteria
- [ ] orchestrator routes to the right agent
- [ ] deterministic pipelines for swaps/messages
- [ ] observable run traces

## Dependencies
TASK-012, TASK-043

## Refs
Requirements §20 ST5

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status

| Task | Status | What it provides |
|---|---|---|
| TASK-012 (LLM abstraction) | IN-PROGRESS — `backend/app/llm.py` fully implemented | `chat()`, `json_chat()` with tenacity retries + fence-stripping; `get_client()` singleton |
| TASK-043 (Orchestrator endpoint) | IN-PROGRESS — analysis done, code not yet written | `POST /orchestrate` (command-bar → WidgetSpec[]); **separate concern from TASK-053** |

**Verdict:** TASK-012 is materially satisfied. TASK-043 and TASK-053 are sibling concerns — TASK-043 handles the synchronous command-bar widget-spec path; TASK-053 creates the async LangGraph domain-agent layer. They share no code surface.

### Architectural Separation: TASK-043 vs TASK-053

| | TASK-043 | TASK-053 |
|---|---|---|
| Purpose | Command-bar → widget specs | RM request/event → domain-agent pipeline |
| Latency | Synchronous, ~1s | Async background task, seconds-to-minutes |
| Output | `WidgetSpec[]` for the generative UI | `Task.result` JSONB (cited brief / swap list / draft) |
| Uses LangGraph? | No — simple LLM classifier | Yes — `StateGraph` with conditional edges |
| Entry point | `POST /orchestrate` (HTTP) | `graph.ainvoke()` called by research_runner / future tasks |

### Existing Resources Found

- **`backend/app/llm.py`** — `json_chat(messages, schema)` for the router classification node; `chat()` for prose nodes
- **`backend/app/models/enums.py:88–106`** — `TaskKind` enum already defines the closed routing vocabulary: `RESEARCH`, `NEWS_GATHER`, `SWAP_CANDIDATES`, `DRAFT_PREP`, `ANALYSIS`, `CONTACT_CLIENT`, `PLACE_ORDER`, `SEND_MESSAGE`, `CRM_WRITEBACK`
- **`backend/app/loaders/dna.py`** — CRM Agent source; DNA extraction and enrichment
- **`backend/app/loaders/drift.py`** — Portfolio Agent: drift detection (±2pp rule)
- **`backend/app/loaders/fit.py`** — Portfolio Agent: fit score per holding
- **`backend/app/loaders/swap.py`** — Portfolio Agent: CIO-BUY swap candidate engine (deterministic pipeline, `FIT_GAIN_THRESHOLD`)
- **`backend/app/loaders/news_match.py`** — News Agent: two-axis client-news matcher
- **`backend/app/news.py`** — News Agent: `search_articles(keywords, count)` for on-demand Event Registry fetch
- **`backend/app/loaders/message_render.py`** — Message Agent: style-profile render + hallucination guardrail
- **`backend/app/loaders/fact_sheet.py`** — Message Agent: fact assembly
- **`backend/app/redis_client.py`** — `dequeue("task_queue")` / `enqueue()` — existing FIFO queue backbone
- **`backend/app/models/derived.py`** — `Task.result` (JSONB) already typed for `{summary, sources, log}` output
- **`backend/app/loaders/task_classify.py`** — `assert_auto_eligible()` guard (TK3); reuse at router node
- **`backend/app/logging.py`** — `get_logger()` for structured trace logging

### Dependencies Required

- **Backend packages** — add to `requirements.txt`:
  - `langgraph>=0.2,<1.0` — LangGraph `StateGraph` + conditional edges; compatible with pydantic 2.x and openai 1.54
  - _(transitive: `langchain-core>=0.2` pulled by langgraph — verify no conflict with `httpx>=0.23,<0.28` pinned for openai)_
- **Frontend packages**: none
- **Database migrations**: none — `Task.result` JSONB already accommodates the graph output
- **Docker services**: none new — same Ollama/Postgres/Redis services used throughout

### Impact Assessment

#### Files to Create
- `backend/app/agents/__init__.py`: package init; exports `graph`, `AgentState`, `AgentRequest`
- `backend/app/agents/state.py`: `AgentState` TypedDict (shared graph state); `AgentRequest` input model
- `backend/app/agents/nodes.py`: 5 node functions — `route_intent`, `crm_agent`, `portfolio_agent`, `news_agent`, `message_agent`; each appends to `state["trace"]`
- `backend/app/agents/graph.py`: `StateGraph` assembly — nodes + conditional edges + compile; exports compiled `graph`

#### Files to Modify
- `backend/requirements.txt`: add `langgraph>=0.2,<1.0` under `# --- TASK-053` comment

#### Files NOT changed
- `backend/app/main.py` — graph is imported by callers (research_runner), not wired into lifespan
- `backend/app/loaders/` — all loaders are imported by agent nodes; no modification to loaders
- `backend/app/routers/` — no new HTTP endpoint for TASK-053 itself

#### Components Affected
- `backend/app/loaders/research_runner.py` (TASK-051) — HIGH: should call `graph.ainvoke()` instead of ad-hoc tool calls; TASK-053 must land first
- `TASK-054 domain-agent wiring` — HIGH: domain agent nodes in `nodes.py` become the integration points for TASK-054's richer agent logic
- `backend/requirements.txt` — LOW: additive only; langgraph's transitive deps need version-conflict check

### State Schema

```python
# backend/app/agents/state.py
from typing import TypedDict, Literal, Any

class AgentState(TypedDict):
    task_kind: str          # TaskKind.value — the routing key
    client_id: str | None   # UUID string; None for non-client tasks (e.g. market scan)
    input: str              # original request / task title from Task.title
    result: dict[str, Any]  # accumulated result; written to Task.result on completion
    trace: list[str]        # TK5 observable action log; one entry per node step
    error: str | None       # set if a node fails; graph short-circuits to END
```

### LangGraph Graph Structure

```
START
  │
  ▼
route_intent_node ──(uses json_chat if task_kind unknown)──► classifies into one of 5 branches
  │
  ├── "crm" / "research" ──────────────────────────► crm_agent_node ──────────► END
  ├── "portfolio" / "swap_candidates" ─────────────► portfolio_agent_node ────► END  (deterministic)
  ├── "news" / "news_gather" ────────────────────── ► news_agent_node ─────────► END
  ├── "message" / "draft_prep" ──────────────────── ► message_agent_node ──────► END  (deterministic)
  └── unknown ────────────────────────────────────── ► fallback_node ───────────► END
```

**Deterministic pipeline constraint (AC #2):**
- `portfolio_agent_node` always runs: `load_drift → score_fit → find_swaps → END` with no looping edges
- `message_agent_node` always runs: `load_style_profile → assemble_facts → render_draft → END`
- Neither node feeds back into the router; the graph is a DAG for these paths
- LLM is only used in: `route_intent_node` (classification) and `message_agent_node` (prose render only)

**Observable run traces (AC #3):**
Each node function appends a structured string to `state["trace"]` before returning:
```python
state["trace"].append(f"[portfolio_agent] scored {n} holdings, found {k} swap candidates")
```
The final `state["trace"]` list is written verbatim into `Task.result["log"]` — satisfying TK5 reviewability.

### Node Responsibilities

| Node | Input used | Loaders called | Output written to `result` |
|---|---|---|---|
| `route_intent` | `task_kind`, `input` | `json_chat` (only if kind=unknown) | `task_kind` (resolved) |
| `crm_agent` | `client_id` | `loaders.dna` | `result["dna_summary"]`, citations |
| `portfolio_agent` | `client_id` | `loaders.drift`, `loaders.fit`, `loaders.swap` | `result["drift"]`, `result["swaps"]` |
| `news_agent` | `client_id`, `input` | `news.search_articles`, `loaders.news_match` | `result["news_items"]` |
| `message_agent` | `client_id`, `result` (prior steps) | `loaders.fact_sheet`, `loaders.message_render` | `result["draft_text"]` |

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Add `langgraph>=0.2,<1.0` to `backend/requirements.txt`
- [ ] Create `backend/app/agents/state.py` with `AgentState` TypedDict and `AgentRequest` model
- [ ] Create `backend/app/agents/nodes.py`:
  - [ ] `route_intent(state)`: if `task_kind` already set, pass through; else `json_chat` to classify
  - [ ] `crm_agent(state)`: call DNA loaders; append trace entry; set `result["dna_summary"]`
  - [ ] `portfolio_agent(state)`: drift → fit → swap pipeline; **no looping edges** (AC #2); append trace
  - [ ] `news_agent(state)`: `search_articles` + `match_articles`; append trace
  - [ ] `message_agent(state)`: fact_sheet → message_render; append trace; `result["draft_text"]`
  - [ ] All nodes catch exceptions and set `state["error"]`; do not raise (graph short-circuits)
- [ ] Create `backend/app/agents/graph.py`:
  - [ ] Build `StateGraph(AgentState)`, add all nodes
  - [ ] `add_conditional_edges("route_intent", _routing_fn, {...})` — maps task_kind → node name
  - [ ] Each domain agent has a direct edge to `END`
  - [ ] Compile: `graph = workflow.compile()`
  - [ ] Export `graph` as the public symbol
- [ ] Create `backend/app/agents/__init__.py`: `from app.agents.graph import graph; from app.agents.state import AgentState, AgentRequest`
- [ ] Reuse `get_logger()` — no `print()` statements
- [ ] Reuse `assert_auto_eligible()` in route_intent to block Manual-only kinds (TK3 guard)
- [ ] Follow SOLID: nodes have no FastAPI imports; graph module has no DB imports; DB calls stay in loader functions
- [ ] Smoke test: `await graph.ainvoke({"task_kind": "portfolio", "client_id": "<uuid>", "input": "check swaps", "result": {}, "trace": [], "error": None})`

### Risk Analysis
- **Risk Level**: LOW–MEDIUM
- **Main Risks**:
  - **langgraph transitive deps**: `langchain-core` pulled by langgraph may bump `httpx` or `pydantic` beyond the pinned ranges. Mitigation: check `pip install langgraph --dry-run` against existing pins before committing; `langchain-core>=0.2` and pydantic v2 are compatible.
  - **TASK-051 dependency order**: `research_runner.py` (TASK-051) should call `graph.ainvoke()` but was analysed without LangGraph. Mitigation: TASK-053 must merge before TASK-051's implementation; the research_runner becomes a thin dequeue-and-invoke wrapper (~30 lines vs 150).
  - **LLM unavailable in router node**: if the LLM is down and `task_kind` is unknown, the router can't classify. Mitigation: if `task_kind` is already set (explicit from Task model), skip LLM call entirely — most invocations from research_runner will have an explicit `TaskKind`.
  - **Demo time constraint**: LangGraph adds a non-trivial dependency. If integration issues arise during the hackathon demo window, fallback is to inline the routing logic in `research_runner.py` without LangGraph (same AC satisfaction, just no StateGraph).

### Estimated Effort
- Original: M
- Adjusted: M (confirmed)
- Reason: All domain loaders exist; this is wiring them into a typed graph. The core graph is ~80 lines; each node is ~30 lines reusing existing loader calls. The main risk is langgraph dep compatibility, not implementation complexity.
