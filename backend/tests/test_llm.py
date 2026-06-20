"""Unit tests for backend/app/llm.py (TASK-012).

Tests are network-free: _strip_fences is a pure function; json_chat is tested
by patching chat() so no LLM endpoint is required.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.llm import _strip_fences, json_chat


# ---------------------------------------------------------------------------
# _strip_fences — pure function, no mocking needed
# ---------------------------------------------------------------------------

def test_strip_fences_bare_json():
    raw = '{"key": "value"}'
    assert _strip_fences(raw) == raw


def test_strip_fences_markdown_json_fence():
    raw = '```json\n{"key": "value"}\n```'
    assert _strip_fences(raw) == '{"key": "value"}'


def test_strip_fences_plain_code_fence():
    raw = '```\n{"key": "value"}\n```'
    assert _strip_fences(raw) == '{"key": "value"}'


def test_strip_fences_json_in_prose():
    raw = 'Here is the result: {"key": "value"} as requested.'
    assert _strip_fences(raw) == '{"key": "value"}'


def test_strip_fences_array():
    raw = '[1, 2, 3]'
    assert _strip_fences(raw) == '[1, 2, 3]'


def test_strip_fences_passthrough_when_no_json():
    raw = "just prose with no JSON"
    assert _strip_fences(raw) == raw


# ---------------------------------------------------------------------------
# json_chat — patched chat() so no network is needed
# ---------------------------------------------------------------------------

class _SampleSchema(BaseModel):
    answer: str
    score: float


@pytest.mark.asyncio
async def test_json_chat_valid_json():
    payload = '{"answer": "hello", "score": 0.9}'
    with patch("app.llm.chat", new=AsyncMock(return_value=payload)):
        result = await json_chat(
            [{"role": "user", "content": "test"}],
            _SampleSchema,
        )
    assert result.answer == "hello"
    assert result.score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_json_chat_fenced_json():
    payload = "```json\n{\"answer\": \"world\", \"score\": 0.5}\n```"
    with patch("app.llm.chat", new=AsyncMock(return_value=payload)):
        result = await json_chat(
            [{"role": "user", "content": "test"}],
            _SampleSchema,
        )
    assert result.answer == "world"


@pytest.mark.asyncio
async def test_json_chat_raises_after_retries():
    with patch("app.llm.chat", new=AsyncMock(return_value="not json at all")):
        with pytest.raises(json.JSONDecodeError):
            await json_chat(
                [{"role": "user", "content": "test"}],
                _SampleSchema,
            )
