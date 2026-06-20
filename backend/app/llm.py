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
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logging import get_logger

T = TypeVar("T", bound=BaseModel)

settings = get_settings()
log = get_logger(__name__)

_client: AsyncOpenAI | None = None

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
    """Single-turn chat completion; returns the assistant message content."""
    client = get_client()
    resp = await client.chat.completions.create(
        model=model or settings.llm.model,
        messages=messages,
        temperature=temperature,
        max_tokens=_effective_max_tokens(max_tokens),
    )
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
