"""Unit tests for backend/app/graph_mail.py (TASK-060, EPIC-08).

Pure parsing helpers need no mocking. fetch_recent_messages is exercised with a
monkeypatched token + httpx client so no network is touched; it must raise loud on
an HTTP error (no-fallbacks).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import graph_mail as gm
from app.graph_mail import GraphMessage, _html_to_text, _parse_message, fetch_recent_messages


def test_html_to_text_strips_tags_and_collapses():
    assert _html_to_text("<p>Hello   <b>world</b></p>") == "Hello world"
    assert _html_to_text("") is None
    assert _html_to_text(None) is None


def test_parse_message_flattens_graph_resource():
    raw = {
        "id": "AAA",
        "conversationId": "CONV1",
        "subject": "Sell Nestle",
        "bodyPreview": "preview text",
        "body": {"contentType": "html", "content": "<div>Please sell <b>Nestle</b></div>"},
        "from": {"emailAddress": {"name": "Clara Bauer", "address": "clara@ex.com"}},
        "toRecipients": [{"emailAddress": {"name": "RM", "address": "rm@bank.com"}}],
        "receivedDateTime": "2026-06-20T10:00:00Z",
    }
    m = _parse_message(raw)
    assert m.id == "AAA"
    assert m.conversation_id == "CONV1"
    assert m.from_address == "clara@ex.com"
    assert m.body_text == "Please sell Nestle"  # HTML stripped, preferred over preview
    assert m.to_recipients == [("RM", "rm@bank.com")]
    assert m.received_at == datetime(2026, 6, 20, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_message_falls_back_to_preview_when_no_body():
    raw = {"id": "B", "bodyPreview": "just a preview", "body": {"content": ""}}
    assert _parse_message(raw).body_text == "just a preview"


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


@pytest.mark.asyncio
async def test_fetch_recent_messages_parses_and_sends_query(monkeypatch):
    monkeypatch.setattr(gm, "_token", AsyncMock(return_value="tok"))
    captured: dict = {}

    async def fake_get(url, params=None, headers=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _FakeResponse(
            {
                "value": [
                    {
                        "id": "1",
                        "conversationId": "c1",
                        "from": {"emailAddress": {"address": "a@b.com"}},
                        "receivedDateTime": "2026-06-20T09:00:00Z",
                    }
                ]
            }
        )

    monkeypatch.setattr(gm, "_get_client", lambda: SimpleNamespace(get=fake_get))

    msgs = await fetch_recent_messages("rm@bank.com", top=10)

    assert len(msgs) == 1 and isinstance(msgs[0], GraphMessage)
    assert "$select" in captured["params"] and captured["params"]["$top"] == 10
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert "users/rm@bank.com/messages" in captured["url"]


@pytest.mark.asyncio
async def test_fetch_recent_messages_raises_loud_on_http_error(monkeypatch):
    monkeypatch.setattr(gm, "_token", AsyncMock(return_value="tok"))

    async def fake_get(url, params=None, headers=None):
        return _FakeResponse({}, status=500)

    monkeypatch.setattr(gm, "_get_client", lambda: SimpleNamespace(get=fake_get))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_recent_messages("rm@bank.com")
