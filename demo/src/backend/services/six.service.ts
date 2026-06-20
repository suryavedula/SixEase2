import axios, { AxiosInstance } from "axios";
import { IntegrationProbe, StockData } from "../../shared/types";
import { maskToken, preview } from "./probe";

// The SIX Financial Data API is exposed as a streamable-http MCP server
// (JSON-RPC over HTTP), NOT a plain REST API. See docs/SIX_MCP.md. We address
// instruments by Valor and listings (instrument-on-a-venue) by `{valor}_{mic}`.
const DEFAULT_SIX_MCP_URL =
  "https://ca-mcpwebapi-tools.nicepebble-599ed11f.westeurope.azurecontainerapps.io/mcp";

export interface SixInstrument {
  isin: string;
  name: string;
  type: string;
  valor: string;
  mic: string;
  exchange: string;
  issuer: string;
}

interface RpcContent {
  type: string;
  text?: string;
}

interface RpcResult {
  isError?: boolean;
  content?: RpcContent[];
}

interface RpcResponse {
  error?: unknown;
  result?: RpcResult;
}

export class SixService {
  private client: AxiosInstance;
  private readonly url: string;
  private readonly authPreview: string;
  readonly configured: boolean;

  constructor() {
    const token = process.env.SIX_MCP_TOKEN || process.env.SIX_API_KEY || "";
    this.url = process.env.SIX_MCP_URL || DEFAULT_SIX_MCP_URL;
    this.authPreview = maskToken(token);
    this.configured = Boolean(token) && !token.startsWith("your_");

    if (!this.configured) {
      console.warn("[SIX] MCP token not configured; set SIX_MCP_TOKEN");
    }

    this.client = axios.create({
      baseURL: this.url,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
        Authorization: token.startsWith("Bearer ") ? token : `Bearer ${token}`,
      },
      timeout: 30000,
    });
  }

  /** Invoke a SIX MCP tool via JSON-RPC, returning the concatenated text content. */
  private async callTool(name: string, args: Record<string, unknown>): Promise<string> {
    const { data } = await this.client.post("", {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name, arguments: args },
    });

    const payload: RpcResponse = typeof data === "string" ? this.parseRpcPayload(data) : data;

    if (payload?.error) {
      throw new Error(`tool ${name}: ${JSON.stringify(payload.error)}`);
    }

    const result = payload?.result;
    const text = (result?.content || [])
      .filter((c) => c.type === "text")
      .map((c) => c.text || "")
      .join("\n");

    if (result?.isError) {
      throw new Error(`tool ${name} returned error: ${text.slice(0, 200)}`);
    }
    return text;
  }

  /**
   * streamable-http transports may answer either as plain JSON or with
   * Server-Sent-Events framing (`data: {...}`). Extract the JSON-RPC body
   * from whichever shape we get.
   */
  private parseRpcPayload(raw: string): RpcResponse {
    const trimmed = raw.trim();
    try {
      return JSON.parse(trimmed);
    } catch {
      for (const line of trimmed.split("\n")) {
        const l = line.trim();
        if (l.startsWith("data:")) {
          const json = l.slice(5).trim();
          if (json && json !== "[DONE]") {
            try {
              return JSON.parse(json);
            } catch {
              /* keep scanning */
            }
          }
        }
      }
      throw new Error("[SIX] could not parse MCP response payload");
    }
  }

  /** SIX tools return tab-delimited tables; parse into row objects keyed by header. */
  private parseTable(text: string): Record<string, string>[] {
    const lines = text.trim().split("\n").filter((l) => l.length > 0);
    if (lines.length < 2) return [];
    const header = lines[0].split("\t");
    return lines.slice(1).map((line) => {
      const cells = line.split("\t");
      const row: Record<string, string> = {};
      header.forEach((h, i) => (row[h] = cells[i] ?? ""));
      return row;
    });
  }

  /** Free-text instrument search. Returns hits ranked by SIX's score. */
  async findInstrument(text: string, size = 5): Promise<SixInstrument[]> {
    const raw = await this.callTool("find_instrument", { text, size });
    return this.parseTable(raw).map((r) => ({
      isin: r["hit.isin"] || "",
      name: r["hit.instrumentShortName"] || "",
      type: r["hit.instrumentType"] || "",
      valor: r["hit.valor"] || "",
      mic: r["hit.mostLiquidMarket.mic"] || "",
      exchange: r["hit.mostLiquidMarket.shortName"] || "",
      issuer: r["hit.issuer.longName"] || "",
    }));
  }

  /**
   * Resolve a symbol/name to its most-liquid listing and pull the latest
   * end-of-day price. Chains find_instrument -> end_of_day_snapshot + listing_base.
   */
  async getStockPrice(symbol: string): Promise<StockData> {
    if (!this.configured) {
      throw new Error("[SIX] not configured: set SIX_MCP_TOKEN");
    }

    const hits = await this.findInstrument(symbol, 5);
    const hit = hits.find((h) => h.valor && h.mic);
    if (!hit) throw new Error(`[SIX] no instrument found for "${symbol}"`);

    const listingId = `${hit.valor}_${hit.mic}`;

    const [snapRows, listingRows] = await Promise.all([
      this.callTool("end_of_day_snapshot", {
        mode: "execute",
        listing_ids: [listingId],
        fields: ["close.value", "close.timestamp", "open.value"],
      }).then((t) => this.parseTable(t)),
      this.callTool("listing_base", {
        mode: "execute",
        listing_ids: [listingId],
        fields: ["ticker", "listingCurrency", "listingShortName"],
      }).then((t) => this.parseTable(t)),
    ]);

    const snap = snapRows[0] || {};
    const listing = listingRows[0] || {};

    const close = parseFloat(snap["close.value"]);
    if (!Number.isFinite(close)) {
      // The most-liquid listing may have no EOD data (illiquid MIC, holiday).
      throw new Error(
        `[SIX] no end-of-day price for ${listingId} (${hit.name}); try another venue`
      );
    }
    const open = parseFloat(snap["open.value"]);
    const hasOpen = Number.isFinite(open);
    const change = hasOpen ? close - open : 0;

    return {
      symbol: listing["ticker"] || symbol,
      name: hit.name || listing["listingShortName"] || symbol,
      currentPrice: parseFloat(close.toFixed(2)),
      currency: listing["listingCurrency"] || "USD",
      change: parseFloat(change.toFixed(2)),
      changePercent: hasOpen && open !== 0 ? parseFloat(((change / open) * 100).toFixed(2)) : 0,
      timestamp: snap["close.timestamp"] || new Date().toISOString(),
    };
  }

  /** Liveness check that captures the full request/response for the status UI. */
  async ping(): Promise<IntegrationProbe> {
    const started = Date.now();
    const body = {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name: "get_datetime", arguments: {} },
    };
    const request = {
      method: "POST",
      url: this.url,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
        Authorization: this.authPreview,
      },
      body,
    };

    if (!this.configured) {
      return {
        name: "SIX Financial Data (MCP)",
        configured: false,
        ok: false,
        durationMs: 0,
        request,
        error: "SIX_MCP_TOKEN not set",
      };
    }

    try {
      const raw = await this.callTool("get_datetime", {});
      return {
        name: "SIX Financial Data (MCP)",
        configured: true,
        ok: true,
        durationMs: Date.now() - started,
        request,
        response: { body: preview(raw.trim()) },
      };
    } catch (error) {
      return {
        name: "SIX Financial Data (MCP)",
        configured: true,
        ok: false,
        durationMs: Date.now() - started,
        request,
        error: (error as Error).message,
      };
    }
  }
}
