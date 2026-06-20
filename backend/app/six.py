"""SIX Financial Data MCP client (TASK-013, EPIC-03).

SIX exposes market data as a streamable-http MCP server (JSON-RPC over HTTP),
not a REST API. This module is the Python port of demo/src/backend/services/
six.service.ts. Singleton async client; public API mirrors the TS service.

Identifier conventions (the #1 source of errors — see docs/SIX_MCP.md §1):
  • Instrument tools (instrument_base, instrument_symbology, instrument_markets,
    entity_base): pass  valors=["645156"]
  • Listing/price tools (listing_base, end_of_day_snapshot, intraday_snapshot,
    market_base):         pass  listing_ids=["645156_XNAS"]   ({valor}_{mic})
  • Bulk ISIN resolution: execute_graphql with scheme=ISIN

Public API:
  find_instrument(text, size)   → list[SixInstrument]
  get_eod_snapshot(listing_id)  → EodSnapshot
  get_intraday_snapshot(listing_id) → IntradaySnapshot
  resolve_by_isin(isin)         → SixInstrument
  ping_six()                    → bool   (lifespan health check)
  close_six()                   → None   (lifespan shutdown)
"""

import json
import math
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

_client: httpx.AsyncClient | None = None


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------


class SixInstrument(BaseModel):
    isin: str
    name: str
    type: str
    valor: str
    mic: str
    exchange: str
    issuer: str


class EodSnapshot(BaseModel):
    listing_id: str
    close: float
    open: float | None
    timestamp: str
    currency: str
    volume: float | None


class IntradaySnapshot(BaseModel):
    listing_id: str
    last: float
    volume: float | None
    timestamp: str


# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------


def _get_client() -> httpx.AsyncClient:
    """Lazy singleton — built once from settings, reused process-wide."""
    global _client
    if _client is None:
        token = settings.six_mcp_token
        if not token:
            log.warning("six.no_token", hint="set SIX_MCP_TOKEN to enable market data")
        _client = httpx.AsyncClient(
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
            },
            timeout=30.0,
        )
        log.info("six.init", url=settings.six_mcp_url)
    return _client


async def close_six() -> None:
    """Release the HTTP connection pool on app shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        log.info("six.closed")


# ---------------------------------------------------------------------------
# Private helpers (ported from six.service.ts)
# ---------------------------------------------------------------------------


def _parse_rpc_payload(raw: str) -> dict[str, Any]:
    """Handle SIX's dual response format: plain JSON or SSE-framed data: {...}.

    streamable-http transports may respond with either a bare JSON-RPC object
    or one/more Server-Sent-Events lines. We try plain JSON first; if that
    fails we scan for the first parseable `data:` line.
    """
    trimmed = raw.strip()
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        pass
    for line in trimmed.splitlines():
        stripped = line.strip()
        if stripped.startswith("data:"):
            payload = stripped[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
    raise ValueError("[SIX] could not parse MCP response payload")


def _parse_table(text: str) -> list[dict[str, str]]:
    """Parse SIX's tab-delimited table responses into row dicts keyed by header."""
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        cells = line.split("\t")
        rows.append({h: cells[i] if i < len(cells) else "" for i, h in enumerate(headers)})
    return rows


async def _call_tool(name: str, args: dict[str, Any]) -> str:
    """Invoke a SIX MCP tool via JSON-RPC, returning concatenated text content."""
    client = _get_client()
    response = await client.post(
        settings.six_mcp_url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        },
    )
    response.raise_for_status()

    raw = response.text
    payload = _parse_rpc_payload(raw)

    if payload.get("error"):
        raise ValueError(f"[SIX] tool {name} error: {json.dumps(payload['error'])}")

    result = payload.get("result", {})
    content = result.get("content") or []
    text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")

    if result.get("isError"):
        raise ValueError(f"[SIX] tool {name} returned error: {text[:200]}")

    return text


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def find_instrument(text: str, size: int = 5) -> list[SixInstrument]:
    """Free-text instrument search ranked by SIX score."""
    raw = await _call_tool("find_instrument", {"text": text, "size": size})
    return [
        SixInstrument(
            isin=r.get("hit.isin", ""),
            name=r.get("hit.instrumentShortName", ""),
            type=r.get("hit.instrumentType", ""),
            valor=r.get("hit.valor", ""),
            mic=r.get("hit.mostLiquidMarket.mic", ""),
            exchange=r.get("hit.mostLiquidMarket.shortName", ""),
            issuer=r.get("hit.issuer.longName", ""),
        )
        for r in _parse_table(raw)
        if r.get("hit.valor")
    ]


async def get_eod_snapshot(listing_id: str) -> EodSnapshot:
    """End-of-day price snapshot for a listing (e.g. '645156_XNAS').

    Raises ValueError if the listing has no settled close price.
    """
    raw = await _call_tool(
        "end_of_day_snapshot",
        {
            "mode": "execute",
            "listing_ids": [listing_id],
            "fields": [
                "close.value",
                "close.timestamp",
                "open.value",
                "close.volume",
                "listingCurrency",
            ],
        },
    )
    rows = _parse_table(raw)
    row = rows[0] if rows else {}

    close_str = row.get("close.value", "")
    try:
        close = float(close_str)
    except (ValueError, TypeError):
        close = float("nan")

    if not math.isfinite(close):
        raise ValueError(
            f"[SIX] no end-of-day close for {listing_id} "
            "(illiquid venue or non-trading day)"
        )

    open_str = row.get("open.value", "")
    try:
        open_val: float | None = float(open_str)
        if not math.isfinite(open_val):
            open_val = None
    except (ValueError, TypeError):
        open_val = None

    vol_str = row.get("close.volume", "")
    try:
        volume: float | None = float(vol_str)
    except (ValueError, TypeError):
        volume = None

    return EodSnapshot(
        listing_id=listing_id,
        close=close,
        open=open_val,
        timestamp=row.get("close.timestamp", ""),
        currency=row.get("listingCurrency", ""),
        volume=volume,
    )


async def get_intraday_snapshot(listing_id: str) -> IntradaySnapshot:
    """Intraday last price for a listing (e.g. '645156_XNAS')."""
    raw = await _call_tool(
        "intraday_snapshot",
        {
            "mode": "execute",
            "listing_ids": [listing_id],
            "fields": ["last", "volume", "timestamp"],
        },
    )
    rows = _parse_table(raw)
    row = rows[0] if rows else {}

    last_str = row.get("last", "")
    try:
        last = float(last_str)
    except (ValueError, TypeError):
        raise ValueError(f"[SIX] no intraday last price for {listing_id}")

    vol_str = row.get("volume", "")
    try:
        volume: float | None = float(vol_str)
    except (ValueError, TypeError):
        volume = None

    return IntradaySnapshot(
        listing_id=listing_id,
        last=last,
        volume=volume,
        timestamp=row.get("timestamp", ""),
    )


async def resolve_by_isin(isin: str) -> SixInstrument:
    """Resolve an ISIN to a SixInstrument via instrument_symbology + find_instrument.

    Uses execute_graphql batch lookup to get the Valor, then fetches full
    instrument details via find_instrument for consistent field population.
    """
    gql = """
query($ids:[UserInputId!]!){
  instruments(ids:$ids, scheme:ISIN){
    referenceData{
      instrumentInfo{ valorNumber isin instrumentShortName instrumentType }
      entityInfo{ longName }
    }
    marketData{ mostLiquidMarket{ mic shortName } }
  }
}
""".strip()

    raw = await _call_tool("execute_graphql", {"query": gql, "variables": {"ids": [isin]}})

    try:
        data = json.loads(raw)
        instruments = (
            data.get("data", {}).get("instruments") or
            data.get("instruments") or
            []
        )
        if instruments:
            inst = instruments[0]
            ref = inst.get("referenceData", {})
            info = ref.get("instrumentInfo", {})
            entity = ref.get("entityInfo", {})
            market = inst.get("marketData", {}).get("mostLiquidMarket", {})
            valor = str(info.get("valorNumber", ""))
            if valor:
                return SixInstrument(
                    isin=info.get("isin", isin),
                    name=info.get("instrumentShortName", ""),
                    type=info.get("instrumentType", ""),
                    valor=valor,
                    mic=market.get("mic", ""),
                    exchange=market.get("shortName", ""),
                    issuer=entity.get("longName", ""),
                )
    except (json.JSONDecodeError, KeyError, IndexError):
        pass

    # Fallback: text search — less reliable but works if GraphQL shape changes
    hits = await find_instrument(isin, size=1)
    if not hits:
        raise ValueError(f"[SIX] could not resolve ISIN {isin}")
    return hits[0]


async def ping_six() -> bool:
    """Lightweight connectivity check using the get_datetime tool."""
    try:
        await _call_tool("get_datetime", {})
        return True
    except Exception as exc:
        log.warning("six.ping_failed", url=settings.six_mcp_url, error=str(exc))
        return False
