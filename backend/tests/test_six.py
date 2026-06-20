"""Unit tests for backend/app/six.py (TASK-013).

Pure-function tests run without mocking; async tests mock _call_tool so no
network is needed. Pattern mirrors tests/test_llm.py.
"""

import json
import math
from unittest.mock import AsyncMock, patch

import pytest

from app.six import (
    EodSnapshot,
    IntradaySnapshot,
    SixInstrument,
    _parse_rpc_payload,
    _parse_table,
    find_instrument,
    get_eod_snapshot,
    get_intraday_snapshot,
    ping_six,
)


# ---------------------------------------------------------------------------
# _parse_rpc_payload — pure function
# ---------------------------------------------------------------------------

_PLAIN_PAYLOAD = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "hello"}]}}


def test_parse_rpc_payload_plain_json():
    raw = json.dumps(_PLAIN_PAYLOAD)
    result = _parse_rpc_payload(raw)
    assert result["result"]["content"][0]["text"] == "hello"


def test_parse_rpc_payload_sse_single_line():
    raw = f"data: {json.dumps(_PLAIN_PAYLOAD)}\n"
    result = _parse_rpc_payload(raw)
    assert result["result"]["content"][0]["text"] == "hello"


def test_parse_rpc_payload_sse_with_done_sentinel():
    raw = (
        "data: [DONE]\n"
        f"data: {json.dumps(_PLAIN_PAYLOAD)}\n"
    )
    result = _parse_rpc_payload(raw)
    assert result["result"]["content"][0]["text"] == "hello"


def test_parse_rpc_payload_sse_with_event_prefix():
    raw = (
        "event: message\n"
        f"data: {json.dumps(_PLAIN_PAYLOAD)}\n"
        "\n"
    )
    result = _parse_rpc_payload(raw)
    assert result["result"]["content"][0]["text"] == "hello"


def test_parse_rpc_payload_raises_on_garbage():
    with pytest.raises(ValueError, match="could not parse"):
        _parse_rpc_payload("not json at all\nalso not json")


# ---------------------------------------------------------------------------
# _parse_table — pure function
# ---------------------------------------------------------------------------

def test_parse_table_normal():
    text = "col.a\tcol.b\tcol.c\nval1\tval2\tval3\n"
    rows = _parse_table(text)
    assert len(rows) == 1
    assert rows[0] == {"col.a": "val1", "col.b": "val2", "col.c": "val3"}


def test_parse_table_multiple_rows():
    text = "h1\th2\nA\tB\nC\tD\n"
    rows = _parse_table(text)
    assert len(rows) == 2
    assert rows[1]["h1"] == "C"


def test_parse_table_empty_string():
    assert _parse_table("") == []


def test_parse_table_header_only():
    assert _parse_table("col.a\tcol.b\n") == []


def test_parse_table_short_row_pads_with_empty():
    text = "a\tb\tc\nonly_one\n"
    rows = _parse_table(text)
    assert rows[0]["b"] == ""
    assert rows[0]["c"] == ""


# ---------------------------------------------------------------------------
# find_instrument — async, mocked _call_tool
# ---------------------------------------------------------------------------

_FIND_TAB = (
    "hit.isin\thit.instrumentShortName\thit.instrumentType\t"
    "hit.valor\thit.mostLiquidMarket.mic\thit.mostLiquidMarket.shortName\thit.issuer.longName\n"
    "US0231351067\tAmazon.Com Rg\tEQUITY\t645156\tXNAS\tNASDAQ\tAmazon.com Inc\n"
)


@pytest.mark.asyncio
async def test_find_instrument_returns_instruments():
    with patch("app.six._call_tool", new=AsyncMock(return_value=_FIND_TAB)):
        results = await find_instrument("Amazon")
    assert len(results) == 1
    inst = results[0]
    assert isinstance(inst, SixInstrument)
    assert inst.valor == "645156"
    assert inst.isin == "US0231351067"
    assert inst.mic == "XNAS"
    assert inst.name == "Amazon.Com Rg"


@pytest.mark.asyncio
async def test_find_instrument_empty_table():
    with patch("app.six._call_tool", new=AsyncMock(return_value="")):
        results = await find_instrument("nonexistent")
    assert results == []


# ---------------------------------------------------------------------------
# get_eod_snapshot — async, mocked _call_tool
# ---------------------------------------------------------------------------

_EOD_TAB = (
    "close.value\tclose.timestamp\topen.value\tclose.volume\tlistingCurrency\n"
    "245.22\t2026-06-08T00:00:00Z\t242.00\t12750000\tUSD\n"
)


@pytest.mark.asyncio
async def test_get_eod_snapshot_parses_correctly():
    with patch("app.six._call_tool", new=AsyncMock(return_value=_EOD_TAB)):
        snap = await get_eod_snapshot("645156_XNAS")
    assert isinstance(snap, EodSnapshot)
    assert snap.listing_id == "645156_XNAS"
    assert snap.close == pytest.approx(245.22)
    assert snap.open == pytest.approx(242.00)
    assert snap.currency == "USD"
    assert snap.volume == pytest.approx(12750000)
    assert snap.timestamp == "2026-06-08T00:00:00Z"


@pytest.mark.asyncio
async def test_get_eod_snapshot_raises_on_missing_close():
    bad_tab = "close.value\tclose.timestamp\n\t\n"
    with patch("app.six._call_tool", new=AsyncMock(return_value=bad_tab)):
        with pytest.raises(ValueError, match="no end-of-day close"):
            await get_eod_snapshot("645156_XNAS")


@pytest.mark.asyncio
async def test_get_eod_snapshot_open_none_when_missing():
    tab = (
        "close.value\tclose.timestamp\topen.value\tclose.volume\tlistingCurrency\n"
        "100.0\t2026-06-08\t\t\tCHF\n"
    )
    with patch("app.six._call_tool", new=AsyncMock(return_value=tab)):
        snap = await get_eod_snapshot("12345_XSWX")
    assert snap.open is None
    assert snap.volume is None


# ---------------------------------------------------------------------------
# get_intraday_snapshot — async, mocked _call_tool
# ---------------------------------------------------------------------------

_INTRA_TAB = (
    "last\tvolume\ttimestamp\n"
    "246.10\t3200000\t2026-06-09T14:32:00Z\n"
)


@pytest.mark.asyncio
async def test_get_intraday_snapshot_parses_correctly():
    with patch("app.six._call_tool", new=AsyncMock(return_value=_INTRA_TAB)):
        snap = await get_intraday_snapshot("645156_XNAS")
    assert isinstance(snap, IntradaySnapshot)
    assert snap.last == pytest.approx(246.10)
    assert snap.volume == pytest.approx(3200000)
    assert snap.timestamp == "2026-06-09T14:32:00Z"


@pytest.mark.asyncio
async def test_get_intraday_snapshot_raises_on_missing_last():
    bad = "last\tvolume\n\t\n"
    with patch("app.six._call_tool", new=AsyncMock(return_value=bad)):
        with pytest.raises(ValueError, match="no intraday last price"):
            await get_intraday_snapshot("645156_XNAS")


# ---------------------------------------------------------------------------
# ping_six — async, mocked _call_tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ping_six_returns_true_on_success():
    with patch("app.six._call_tool", new=AsyncMock(return_value="2026-06-20 10:00:00")):
        assert await ping_six() is True


@pytest.mark.asyncio
async def test_ping_six_returns_false_on_error():
    with patch("app.six._call_tool", new=AsyncMock(side_effect=Exception("timeout"))):
        assert await ping_six() is False
