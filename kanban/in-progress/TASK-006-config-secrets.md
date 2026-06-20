# TASK-006: Config and provider secrets

**Status:** IN-PROGRESS · **Epic:** EPIC-01 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20

## Description
Centralise config: provider base URLs/keys (LLM, SIX MCP, Event Registry), DB/redis/minio. Provide .env.example. Single settings object.

## Acceptance Criteria
- [x] .env.example lists every required key
- [x] missing-key warnings logged, not crashes
- [x] one settings import used app-wide

## Dependencies
TASK-002

## Refs
Requirements §20 ST1 (provider abstraction)

## Implementation notes
- `backend/app/config.py`: extended the single `Settings` object with the §20 ST1
  LLM provider abstraction (`LLM_PROVIDER` ∈ ollama|openrouter|phoeniqs, each with
  base URL / key / model), SIX MCP (url + token), and Event Registry (key + url).
  `settings.llm` resolves the active OpenAI-compatible backend (`LLMConfig`);
  unknown provider falls back to the keyless local Ollama path instead of crashing.
- `settings.missing_secrets()` returns the unset keys + the feature each gates
  (only the *active* LLM provider's key is checked; Ollama is keyless). Logged at
  startup in `app/main.py` lifespan as `startup.missing_secret` warnings — never raises.
- `.env.example` + local `.env`: provider section uncommented/finalised; names mirror
  `demo/.env.example` so hackathon credentials drop straight in.
- Single import preserved: `get_settings()` is the only `Settings()` instantiation; all
  modules import it (verified).

> Dependency note: TASK-002 (FastAPI skeleton) is still in `in-progress/`, not `done/`,
> but its config/logging scaffolding this task builds on is present and was extended in place.
