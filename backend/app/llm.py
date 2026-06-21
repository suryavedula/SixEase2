"""OpenAI-compatible LLM client (TASK-012, EPIC-03).

Singleton async client supporting Ollama / OpenRouter / Phoeniqs backends
interchangeably via LLM_PROVIDER config. Public API:

  get_client()  — lazy AsyncOpenAI singleton
  chat()        — raw text completion
  json_chat()   — structured Pydantic output with fence-stripping + retries
  ping_llm()    — startup connectivity check (wired into main.py lifespan)
  close_llm()   — shutdown cleanup (wired into main.py lifespan)
"""
import json
import re
from datetime import datetime, timezone
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logging import get_logger
from app.redis_client import redis_client

T = TypeVar("T", bound=BaseModel)

settings = get_settings()
log = get_logger(__name__)

_client: AsyncOpenAI | None = None


class BudgetExhausted(Exception):
    """Raised when the hosted-LLM token cap for the current UTC day is reached.

    Subclasses `Exception` so existing `except Exception` handlers in callers
    (news_fanout re-enqueue, orchestrate fallback, agents state["error"]) route it
    as a soft, recoverable error — work pauses until the daily meter resets, the
    zero-LLM Change Radar keeps running, and nothing silently switches engines
    (no-fallbacks rule). See routers/admin.py `GET /admin/budget` for the readout.
    """


# --- Token budget meter (always-on safety for the proactive loops) ----------
# Only hosted/paid providers are metered; local Ollama is free and never gated.
# The meter lives in Redis under a per-UTC-day key so it survives restarts and
# resets daily. `settings.phoeniqs_budget_tokens <= 0` disables the cap entirely.
_FREE_PROVIDERS = {"ollama"}


def _is_metered() -> bool:
    return settings.llm.provider not in _FREE_PROVIDERS


def _budget_key() -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"llm:budget:{settings.llm.provider}:{day}"


async def budget_status() -> dict:
    """Spent / cap / remaining for the active provider's current UTC day."""
    cap = settings.phoeniqs_budget_tokens
    metered = _is_metered()
    spent = int(await redis_client.get(_budget_key()) or 0) if metered else 0
    remaining = None if (not metered or cap <= 0) else max(0, cap - spent)
    return {
        "provider": settings.llm.provider,
        "metered": metered,
        "cap": cap,
        "spent": spent,
        "remaining": remaining,
        "exhausted": metered and cap > 0 and spent >= cap,
    }


async def _budget_check() -> None:
    """Raise BudgetExhausted if the metered provider is at/over its daily cap."""
    cap = settings.phoeniqs_budget_tokens
    if not _is_metered() or cap <= 0:
        return
    spent = int(await redis_client.get(_budget_key()) or 0)
    if spent >= cap:
        log.warning("llm.budget_exhausted", provider=settings.llm.provider, spent=spent, cap=cap)
        raise BudgetExhausted(
            f"{settings.llm.provider} token cap reached for today ({spent}/{cap})"
        )


async def _budget_record(total_tokens: int) -> None:
    """Add this call's token usage to the daily meter (metered providers only)."""
    if not _is_metered() or total_tokens <= 0:
        return
    key = _budget_key()
    new_total = await redis_client.incrby(key, total_tokens)
    await redis_client.expire(key, 172800)  # 2-day TTL; keys self-clean
    cap = settings.phoeniqs_budget_tokens
    warn_pct = settings.phoeniqs_budget_warn_pct
    if cap > 0 and warn_pct > 0:
        threshold = cap * warn_pct / 100
        if (new_total - total_tokens) < threshold <= new_total:
            log.warning(
                "llm.budget_warn", provider=settings.llm.provider, spent=new_total, cap=cap, pct=warn_pct
            )

# Reasoning models (e.g. Phoeniqs `inference-gpt-oss-120b`) spend completion-token
# budget on hidden reasoning *before* emitting any content. A `max_tokens` sized
# for a non-reasoning model (Ollama/Gemma) truncates mid-reasoning — the request
# returns finish_reason="length" with empty content, and json_chat then fails to
# parse. Give reasoning providers headroom on top of the caller's requested output
# budget so the visible answer still fits. Non-reasoning providers are untouched.
_REASONING_PROVIDERS = {"phoeniqs"}
_REASONING_HEADROOM = 4096
_REASONING_FLOOR = 6000


def _effective_max_tokens(requested: int) -> int:
    """Add reasoning headroom for reasoning-model providers (see note above)."""
    if settings.llm.provider in _REASONING_PROVIDERS:
        return max(requested + _REASONING_HEADROOM, _REASONING_FLOOR)
    return requested


def get_client() -> AsyncOpenAI:
    """Lazy singleton — built once from settings.llm, reused process-wide."""
    global _client
    if _client is None:
        cfg = settings.llm
        _client = AsyncOpenAI(
            base_url=cfg.base_url,
            # openai SDK rejects an empty api_key string; Ollama ignores the value
            api_key=cfg.api_key or "nokey",
        )
        log.info("llm.init", provider=cfg.provider, model=cfg.model, base_url=cfg.base_url)
    return _client


async def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    """Single-turn chat completion; returns the assistant message content.

    Guarded by the daily token budget (metered providers only): raises
    BudgetExhausted *before* spending if the cap is hit, and records actual
    `usage` after a successful call.
    """
    client = get_client()
    await _budget_check()
    resp = await client.chat.completions.create(
        model=model or settings.llm.model,
        messages=messages,
        temperature=temperature,
        max_tokens=_effective_max_tokens(max_tokens),
    )
    usage = getattr(resp, "usage", None)
    if usage is not None:
        await _budget_record(getattr(usage, "total_tokens", 0) or 0)
    return resp.choices[0].message.content or ""


async def json_chat(
    messages: list[dict],
    schema: type[T],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> T:
    """Chat completion parsed + validated against a Pydantic schema.

    Retries up to 3× on JSONDecodeError / ValidationError, appending the parse
    error as a user message so the model self-corrects on the next attempt.
    """
    active_messages = list(messages)

    @retry(
        retry=retry_if_exception_type((json.JSONDecodeError, ValidationError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def _attempt() -> T:
        content = await chat(
            active_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw = _strip_fences(content)
        parsed = json.loads(raw)
        return schema.model_validate(parsed)

    try:
        return await _attempt()
    except (json.JSONDecodeError, ValidationError) as exc:
        log.warning(
            "llm.json_parse_failed",
            provider=settings.llm.provider,
            schema=schema.__name__,
            error=str(exc),
        )
        raise


def _strip_fences(text: str) -> str:
    """Extract the first JSON object or array from LLM output.

    Handles markdown code fences and prose wrapping — ported from
    demo/src/backend/services/phoeniqs.service.ts:parseJson.
    """
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        return match.group(1)
    return text.strip()


async def ping_llm() -> bool:
    """Lightweight LLM connectivity check for the startup readiness probe."""
    try:
        client = get_client()
        await client.models.list()
        return True
    except Exception as exc:
        log.warning("llm.ping_failed", provider=settings.llm.provider, error=str(exc))
        return False


async def close_llm() -> None:
    """Release the HTTP connection pool on app shutdown."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
        log.info("llm.closed")
