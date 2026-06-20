# TASK-013: SIX MCP client

**Status:** IN-PROGRESS · **Epic:** EPIC-03 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Port the demo six.service to Python: JSON-RPC over streamable-http with SSE handling, tab-table parsing, find_instrument, end_of_day/intraday snapshots, instrument_symbology. Honour Valor / {valor}_{mic} / ISIN conventions.

## Acceptance Criteria
- [ ] resolve instrument and fetch EOD price
- [ ] SSE and plain-JSON responses parsed
- [ ] bonds via instrument_symbology by ISIN

## Dependencies
TASK-006 (IN-PROGRESS — `settings.six_mcp_url` / `settings.six_mcp_token` already live in `backend/app/config.py`)

## Refs
Requirements §10.3, docs/SIX_MCP.md

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Config:** `backend/app/config.py` — `settings.six_mcp_url` and `settings.six_mcp_token` are already defined (TASK-006); no config changes needed
- **Reference implementation:** `demo/src/backend/services/six.service.ts` — full working TS implementation to port: `callTool()`, `parseRpcPayload()` (SSE+JSON duality), `parseTable()` (tab-delimited), `findInstrument()`, `getStockPrice()`, `ping()`
- **Pattern to follow:** `backend/app/llm.py` — singleton module with lazy init, `get_logger()`, `ping_*()` wired into `main.py` lifespan
- **Logger:** `backend/app/logging.py` — `get_logger(__name__)` (structlog)
- **Startup wiring:** `backend/app/main.py` — `ping_llm()` / `close_llm()` pattern, non-fatal try/except in lifespan
- **Services:** No existing Python SIX client anywhere in the backend

### Dependencies Required
- **Backend packages:** `httpx[asyncio]` — async HTTP for JSON-RPC calls; already a transitive dependency via `openai`, but must be pinned explicitly in `requirements.txt`
- **Frontend packages:** none
- **Database migrations:** none (SIX is a read-only external API)
- **Docker services:** none (hits external SIX MCP URL)

### Impact Assessment

#### Files to Create
- `backend/app/six.py` — new SIX MCP client module (main deliverable)

#### Files to Modify
- `backend/requirements.txt` — add `httpx` explicit pin
- `backend/app/main.py` — wire `ping_six()` into lifespan (same pattern as LLM)

#### Components Affected
- `backend/app/main.py`: LOW — add two lines to lifespan (import + non-fatal ping call)
- `backend/requirements.txt`: LOW — one new line

#### API Changes
- None at this stage; `six.py` is a service module, not a router; future tasks mount it

#### Database Changes
- None

### Module Design (`backend/app/six.py`)

Follows the `llm.py` singleton pattern:

```python
# Public API
async def call_tool(name: str, args: dict) -> str   # raw JSON-RPC call → text content
async def find_instrument(text: str, size=5) -> list[SixInstrument]
async def get_eod_price(listing_id: str) -> EodPrice    # e.g. "645156_XNAS"
async def get_intraday(listing_id: str) -> IntradayPrice
async def resolve_isin(isin: str) -> SixInstrument      # via instrument_symbology
async def ping_six() -> bool                           # lifespan health check
```

Key private helpers (ported directly from TS):
- `_parse_rpc_payload(raw)` — handles plain JSON *and* `data: {...}` SSE framing
- `_parse_table(text)` — tab-delimited → `list[dict[str, str]]`
- `_get_client()` — lazy `httpx.AsyncClient` singleton with Bearer token header

### SIX Identifier Convention (from docs/SIX_MCP.md §1, §6)
| Identifier shape | Used for | Parameter name |
|---|---|---|
| `"645156"` (Valor string) | instrument_base, instrument_symbology, instrument_markets, entity_base | `valors: ["645156"]` |
| `"645156_XNAS"` (Valor_MIC) | listing_base, end_of_day_snapshot, intraday_snapshot, market_base | `listing_ids: ["645156_XNAS"]` |
| ISIN string | execute_graphql batch, instrument_symbology lookup | `scheme: ISIN` |

Mixing them up is the #1 error — module docstring will enforce this clearly.

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Use `settings.six_mcp_url` / `settings.six_mcp_token` from existing config (do not duplicate)
- [ ] Follow `llm.py` singleton pattern — one `_client` global, `get_client()` lazy init
- [ ] Port `_parse_rpc_payload()` — handle BOTH plain JSON and SSE `data:` framing (the TS impl is the guide)
- [ ] Port `_parse_table()` — tab-delimited lines, first line = header
- [ ] Implement `ping_six()` via `get_datetime` tool call (same as TS `ping()`)
- [ ] Wire `ping_six()` into `main.py` lifespan (non-fatal, same pattern as `ping_llm()`)
- [ ] Add `httpx` to `requirements.txt` explicitly
- [ ] No new migrations, no frontend changes
- [ ] Follow SOLID principles — single responsibility per method

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - **SSE/JSON duality:** SIX MCP may return either `{"jsonrpc":...}` or `data: {"jsonrpc":...}` SSE framing — mitigated by porting `_parse_rpc_payload()` exactly from TS reference
  - **TASK-006 not yet done:** config keys (`six_mcp_url`, `six_mcp_token`) are already in `config.py`, so this has no practical blocker
  - **`httpx` pin:** currently only a transitive dep; explicit pin prevents surprise version breaks

### Estimated Effort
- Original: M
- Adjusted: M (no change — straightforward port, pattern is clear)
