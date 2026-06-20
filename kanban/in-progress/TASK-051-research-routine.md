# TASK-051: Research routine (auto-run, cited brief)

**Status:** IN-PROGRESS · **Epic:** EPIC-12 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Auto-running research task that gathers from web/news/SIX/CRM and returns a cited, reviewable brief into the canvas/task result; logs what it did. No outward action.

## Acceptance Criteria
- [ ] research brief produced with citations (TK4)
- [ ] actions logged + reviewable (TK5)
- [ ] output is a draft/input only, never an order

## Dependencies
TASK-013, TASK-014, TASK-050

## Refs
Requirements §19.2 TK4/TK5

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **Task model**: `backend/app/models/derived.py` — `Task.result` (JSONB) is already documented as "(cited brief / draft, TK4/TK5, G2)"; zero schema changes needed
- **Task lifecycle API**: `backend/app/routers/tasks.py` — `PATCH /clients/{id}/tasks/{task_id}` accepts `{status, result}` to advance created→running→done
- **Redis queue**: `task_queue` key — `backend/app/routers/tasks.py:160` enqueues `{task_id, client_id}` for every Auto-mode task on creation
- **Autonomy boundary**: `backend/app/loaders/task_classify.py` — `assert_auto_eligible(TaskKind.RESEARCH)` passes; RESEARCH is in `_AUTO_ELIGIBLE`
- **LLM**: `backend/app/llm.py` — `json_chat(messages, Schema)` for structured Pydantic output with 3× retry + fence-strip
- **News client**: `backend/app/news.py` — `search_articles(keywords, count)` for on-demand Event Registry fetch
- **News matching**: `backend/app/loaders/news_match.py` — `match_articles()` two-axis matcher reusable for per-client article relevance scoring
- **SIX client**: `backend/app/six.py` — `get_eod_snapshot(listing_id)`, `find_instrument(text)` for live price context
- **CRM data**: `backend/app/models/source.py` `Interaction` rows — already in DB after seed/crm; chronological notes queryable by `client_id`
- **Client watchlist**: `backend/app/models/derived.py` `ClientWatchlist` — keywords/entities/themes already seeded; reuse for search terms
- **Client DNA**: `backend/app/models/derived.py` `ClientDNA` — values/exclusions/tilts usable to focus brief framing
- **Background task pattern**: `backend/app/loaders/news_fanout.py` and `backend/app/poller.py` — exact pattern to copy: `asyncio.create_task(_loop())`, `SessionFactory`, dequeue-then-act, CancelledError guard
- **Frontend task display**: `frontend/src/components/widgets/TasksList.tsx` — already renders `task.result`; brief can be displayed inline
- **Citation model**: `backend/app/models/citation.py` — `Citation` rows link derived entities to source rows (G2 traceability)

### Dependencies Required

- **Frontend packages**: none new (all existing in `package.json`)
- **Backend packages**: none new (all existing in `requirements.txt` — openai, httpx, structlog, sqlalchemy, redis, tenacity)
- **Database migrations**: none — `Task.result` JSONB already exists
- **Docker services**: Redis (queue), PostgreSQL (task/client/watchlist rows), Ollama/LLM, Event Registry key (NEWSAPI_KEY), SIX MCP token (SIX_MCP_TOKEN)

### Impact Assessment

#### Files to Create
- `backend/app/loaders/research_runner.py`: core research routine — dequeue task_queue, gather CRM/news/SIX, LLM-synthesize cited brief, write result, advance status

#### Files to Modify
- `backend/app/main.py`: import + wire `start_research_runner` / `stop_research_runner` into lifespan alongside poller/fanout (3 lines)
- `frontend/src/components/widgets/TasksList.tsx`: expand `TaskCard` to show `task.result` summary when `status === 'done'` (optional inline expansion)

#### Components Affected
- `backend/app/routers/tasks.py` — read-only; the runner calls the same DB session directly (not via HTTP self-call): LOW
- `backend/app/loaders/news_match.py` — imported for `match_articles` helper: LOW (pure function, no modification)
- `backend/app/six.py` — imported for `get_eod_snapshot`: LOW (existing client)
- `frontend/src/components/widgets/TasksList.tsx` — add brief preview on done tasks: LOW

#### API Changes
- No new endpoints required.
- Existing `PATCH /clients/{id}/tasks/{task_id}` is used internally by the runner to write `result` + transition to `done`.
- Optional: `POST /clients/{id}/tasks/{task_id}/run` — trigger a research run manually for a specific task (useful for testing without waiting for queue dequeue). Medium effort, low risk.

#### Database Changes
- None. `Task.result` JSONB accepts `{summary, sources, gathered_at, log}` without migration.

### Research Brief Schema (proposed)

```python
class ResearchSource(BaseModel):
    type: Literal["crm", "news", "six"]
    ref: str        # interaction_id / news_items.id / listing_id
    quote: str      # short excerpt / headline / price string
    url: str | None

class ResearchBrief(BaseModel):
    summary: str                    # 2-4 sentence cited narrative
    sources: list[ResearchSource]   # TK4 citation chain
    gathered_at: str                # ISO-8601 timestamp
    log: list[str]                  # TK5 action log ("fetched 12 articles", "2 held positions priced via SIX")
```

Stored verbatim as `Task.result` JSONB → satisfies TK4 (cited brief) and TK5 (reviewable log).

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Copy `_fanout_loop` / `start_fanout` / `stop_fanout` pattern from `news_fanout.py` for the runner loop
- [ ] Reuse `search_articles()` from `news.py` — do not re-implement news fetch
- [ ] Reuse `match_articles()` from `news_match.py` to score relevance before passing to LLM
- [ ] Reuse `json_chat()` from `llm.py` for structured brief synthesis
- [ ] Reuse `get_eod_snapshot()` from `six.py` for live prices on held positions
- [ ] Use `assert_auto_eligible(TaskKind.RESEARCH)` at entry point (TK3 guard)
- [ ] Transition task `created → running` before gathering, `running → done` after (TK6)
- [ ] Write `Task.result` as `ResearchBrief` dict — never an order or outward action (G1)
- [ ] Log every gather step via `structlog` with task_id + client_id (TK5)
- [ ] Handle missing keys gracefully (news key absent → skip news gather, log warning)
- [ ] Follow SOLID principles — single `run_research_task()` function; compose from existing loaders

### Risk Analysis

- **Risk Level**: LOW–MEDIUM
- **Main Risks**:
  - **LLM brief quality**: Gemma 3 12B may produce inconsistent JSON for the `ResearchBrief` schema — mitigated by `json_chat()` 3× retry + fence-strip already in place
  - **Missing seeds**: watchlist / CRM may not be seeded in dev — runner should degrade gracefully (return partial brief with what was gathered) rather than fail the task; log clearly
  - **SIX quota**: live price calls consume the 17-tool hackathon token — scope to one `get_eod_snapshot` call per top-held position (e.g. max 3), not bulk
  - **Event Registry rate limit**: 5 concurrent requests max — single sequential runner (same as poller) keeps us within budget

### Estimated Effort
- Original: M
- Adjusted: M
- Reason: All infrastructure exists (queue, LLM, news, SIX, CRM, task model). Implementation is a new ~150-line file + 3-line wiring in main.py + minor frontend addition.
