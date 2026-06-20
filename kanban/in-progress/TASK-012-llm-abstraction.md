# TASK-012: LLM provider abstraction

**Status:** IN-PROGRESS · **Epic:** EPIC-03 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
One OpenAI-compatible client supporting three interchangeable backends by config: Ollama (local Gemma 3 12B), OpenRouter (hosted OSS), Phoeniqs (fallback). JSON/structured output helper + validation.

## Acceptance Criteria
- [ ] switch backend via env only
- [ ] chat + JSON-mode helpers
- [ ] retries + validation for weak small-model output

## Dependencies
TASK-006

## Refs
Requirements §20 ST1/ST1a/ST2

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Config**: `backend/app/config.py` — `LLMConfig` dataclass (`provider`, `base_url`, `api_key`, `model`) and `Settings.llm` property already resolve the active backend from `LLM_PROVIDER`. This is the complete configuration foundation; TASK-012 consumes it, not extends it.
- **Env vars**: `.env.example` §LLM already defines all nine keys (`LLM_PROVIDER`, `OLLAMA_*`, `OPENROUTER_*`, `PHOENIQS_*`). Nothing to add there.
- **Startup logging**: `main.py` lifespan already logs `llm_provider` and `llm_model` on boot.
- **Demo reference**: `demo/src/backend/services/phoeniqs.service.ts` — the JSON fence-stripping pattern (`content.match(/\{[\s\S]*\}/)`) and the `budget_exceeded` → degraded probe pattern are directly portable to Python.
- **`get_settings()`**: `@lru_cache` singleton in `config.py` — import this everywhere, never instantiate `Settings` directly.

### Dependencies Required
- **Add to `backend/requirements.txt`**:
  - `openai>=1.54` — official Python SDK, OpenAI-compatible; works with all three backends via `base_url` + `api_key` override; provides `AsyncOpenAI`, streaming, structured-output helpers
  - `tenacity>=8.5` — retry decorator with exponential back-off; needed for weak-model JSON validation retries (AC #3)
- **No frontend packages** — purely a backend service module
- **No new migrations** — no DB schema changes
- **Docker services**: Ollama service already defined in `docker-compose.yml`; no new service needed

### Impact Assessment

#### Files to Create
- `backend/app/llm.py`: new module — the LLM client singleton + `chat()` + `json_chat()` helpers

#### Files to Modify
- `backend/requirements.txt`: add `openai` and `tenacity` entries under a `# --- TASK-012` comment

#### Files NOT changed
- `backend/app/config.py` — already complete; `LLMConfig` / `settings.llm` are the stable contract
- `backend/app/main.py` — startup logging of provider is already wired
- `.env.example` — already has all nine LLM keys

#### Components Affected
- `TASK-016 dna-extract` — HIGH: first consumer of `llm.json_chat()`
- `TASK-017 style-profile` — HIGH: same
- `TASK-032 alert-generate` — HIGH: alert narrative generation
- `TASK-053 langgraph` — HIGH: orchestrator needs the client
- `TASK-054 domain-agents` — HIGH: all agent prompts route through this
- `TASK-047 note-structuring` — MEDIUM: structured extraction from voice notes

#### API Changes
None — purely internal service module; no FastAPI routes added.

#### Database Changes
None.

### Module Design (`backend/app/llm.py`)

```python
# Three public symbols; everything else is internal:
#   get_client()          → AsyncOpenAI  (cached singleton)
#   chat(messages, **kw)  → str           (raw content)
#   json_chat(messages, schema, **kw) → T  (validated Pydantic model, with retries)

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel
from app.config import get_settings

def get_client() -> AsyncOpenAI:
    cfg = get_settings().llm
    return AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key or "nokey")

async def chat(messages: list[dict], **kwargs) -> str: ...

async def json_chat(messages: list[dict], schema: type[BaseModel], **kwargs) -> BaseModel:
    # 1. request JSON mode
    # 2. fence-strip (TS pattern ported from demo/phoeniqs.service.ts)
    # 3. pydantic parse + validate
    # 4. tenacity retry up to 3× on ValidationError / JSONDecodeError
    ...
```

The singleton should NOT be module-level (avoids import-time side effects and test isolation issues). Callers call `get_client()` → reuse pattern via `@lru_cache` or module-level lazy var.

### Implementation Checklist
- [ ] Add `openai>=1.54` and `tenacity>=8.5` to `requirements.txt`
- [ ] Create `backend/app/llm.py` with `get_client()`, `chat()`, `json_chat()`
- [ ] `get_client()` builds `AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key or "nokey")` — Ollama needs a non-empty key string even though it ignores it
- [ ] `json_chat()` fence-strips before `json.loads` (port from `demo/phoeniqs.service.ts:parseJson`)
- [ ] `json_chat()` uses `tenacity` to retry up to 3× on `ValidationError` / `JSONDecodeError`
- [ ] On retry, append the parse error to messages so the model self-corrects
- [ ] Default `model` comes from `settings.llm.model`; callers can override per call
- [ ] Log provider/model on first call via `structlog` (consistent with `main.py` pattern)
- [ ] Follow SOLID: `llm.py` has no FastAPI imports; it is a pure async service module
- [ ] Write `tests/test_llm.py` with at least: fence-strip logic unit test + Pydantic validation round-trip

### Risk Analysis
- **Risk Level**: LOW
- **Main Risks**:
  - *Ollama empty-key rejection*: `AsyncOpenAI` requires a non-empty `api_key`; pass `"nokey"` for the keyless Ollama path — mitigation: already seen in other OSS Ollama wrappers, well-understood workaround.
  - *Weak-model malformed JSON*: Gemma 3 12B sometimes wraps JSON in markdown fences or adds prose — mitigation: fence-strip + tenacity retries with error feedback in subsequent message.
  - *OpenRouter/Phoeniqs rate limits*: both providers impose request limits — mitigation: tenacity back-off covers transient 429s; long-running callers should implement their own queuing (TASK-053).

### Estimated Effort
- Original: M
- Adjusted: S–M (closer to S)
- Reason: `LLMConfig` + `settings.llm` already done in TASK-006; `.env.example` already complete; module is ~80 lines of focused code with no DB or frontend surface.
