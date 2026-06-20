import axios, { AxiosInstance } from "axios";
import { IntegrationProbe, NewsArticle, PortfolioRecommendation, StockData } from "../../shared/types";
import { maskToken, preview } from "./probe";

// Phoeniqs provides the hackathon LLM credits via an OpenAI-compatible API.
const DEFAULT_PHOENIQS_URL = "https://maas.phoeniqs.com/v1";
const DEFAULT_MODEL = "inference-gpt-oss-120b";

interface LlmRecommendation {
  recommendation?: string;
  confidence?: number;
  reasoning?: string;
  targetPrice?: number | null;
  stopLoss?: number | null;
}

export class PhoeniqsService {
  private client: AxiosInstance;
  private model: string;
  private readonly baseUrl: string;
  private readonly authPreview: string;
  readonly configured: boolean;

  constructor() {
    const apiKey = process.env.PHOENIQS_API_KEY || "";
    this.baseUrl = process.env.PHOENIQS_API_URL || DEFAULT_PHOENIQS_URL;
    this.model = process.env.PHOENIQS_MODEL || DEFAULT_MODEL;
    this.authPreview = maskToken(apiKey);
    this.configured = Boolean(apiKey) && !apiKey.startsWith("your_");

    if (!this.configured) {
      console.warn("[Phoeniqs] API key not configured; set PHOENIQS_API_KEY");
    }

    this.client = axios.create({
      baseURL: this.baseUrl,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      timeout: 60000,
    });
  }

  async analyzePortfolioRecommendation(
    symbol: string,
    currentPrice: number,
    newsSentiment: number,
    marketData: StockData,
    news: NewsArticle[] = []
  ): Promise<PortfolioRecommendation> {
    if (!this.configured) {
      throw new Error("[Phoeniqs] not configured: set PHOENIQS_API_KEY");
    }

    const headlines =
      news.slice(0, 5).map((n) => `- ${n.title}`).join("\n") || "(no recent headlines)";

    const system =
      "You are a buy-side equity analyst. Respond with ONLY a single minified JSON " +
      "object and no surrounding prose or markdown.";

    const user =
      `Analyze the position in ${symbol}.\n` +
      `Current price: ${currentPrice} ${marketData.currency}\n` +
      `Latest day change: ${marketData.changePercent}%\n` +
      `Aggregate news sentiment score (-1 bearish .. 1 bullish): ${newsSentiment}\n` +
      `Recent headlines:\n${headlines}\n\n` +
      `Return JSON with exactly these keys: ` +
      `{"recommendation":"BUY|HOLD|SELL","confidence":<0..1>,` +
      `"reasoning":"<=60 words","targetPrice":<number|null>,"stopLoss":<number|null>}`;

    let data;
    try {
      ({ data } = await this.client.post("/chat/completions", {
        model: this.model,
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        temperature: 0.2,
        max_tokens: 400,
      }));
    } catch (error) {
      const axiosErr = error as { response?: { data?: { error?: { message?: string } } } };
      const msg = axiosErr.response?.data?.error?.message || (error as Error).message;
      throw new Error(`[Phoeniqs] ${msg}`);
    }

    const content: string = data?.choices?.[0]?.message?.content || "";
    const parsed = this.parseJson(content);

    const recommendation = (["BUY", "HOLD", "SELL"] as const).includes(
      parsed.recommendation as PortfolioRecommendation["recommendation"]
    )
      ? (parsed.recommendation as PortfolioRecommendation["recommendation"])
      : "HOLD";

    const confidence =
      typeof parsed.confidence === "number"
        ? parseFloat(Math.max(0, Math.min(1, parsed.confidence)).toFixed(3))
        : 0.5;

    return {
      symbol,
      currentPrice,
      recommendation,
      confidence,
      reasoning: parsed.reasoning || "Insufficient data for detailed analysis",
      suggestedAction: this.mapSuggestedAction(recommendation),
      targetPrice: typeof parsed.targetPrice === "number" ? parsed.targetPrice : undefined,
      stopLoss: typeof parsed.stopLoss === "number" ? parsed.stopLoss : undefined,
    };
  }

  /** Liveness check that captures the full request/response for the status UI. */
  async ping(): Promise<IntegrationProbe> {
    const started = Date.now();
    const request = {
      method: "GET",
      url: `${this.baseUrl}/models`,
      headers: { Authorization: this.authPreview },
    };

    if (!this.configured) {
      return {
        name: "Phoeniqs LLM API",
        configured: false,
        ok: false,
        durationMs: 0,
        request,
        error: "PHOENIQS_API_KEY not set",
      };
    }

    try {
      const res = await this.client.get("/models");
      return {
        name: "Phoeniqs LLM API",
        configured: true,
        ok: true,
        durationMs: Date.now() - started,
        request,
        response: { status: res.status, body: preview(res.data) },
      };
    } catch (error) {
      // A 400 budget_exceeded still proves the endpoint + auth are valid —
      // we surface the full body so the reason is visible.
      const ax = error as { response?: { status?: number; data?: unknown }; message?: string };
      return {
        name: "Phoeniqs LLM API",
        configured: true,
        ok: false,
        durationMs: Date.now() - started,
        request,
        response: ax.response ? { status: ax.response.status, body: preview(ax.response.data) } : undefined,
        error: (error as Error).message,
      };
    }
  }

  /** Tolerate models that wrap JSON in prose or markdown fences. */
  private parseJson(content: string): LlmRecommendation {
    try {
      return JSON.parse(content);
    } catch {
      const match = content.match(/\{[\s\S]*\}/);
      if (match) {
        try {
          return JSON.parse(match[0]);
        } catch {
          /* fall through */
        }
      }
      throw new Error(`could not parse LLM JSON response: ${content.slice(0, 120)}`);
    }
  }

  private mapSuggestedAction(rec: string): PortfolioRecommendation["suggestedAction"] {
    switch (rec) {
      case "BUY":
        return "ADD";
      case "SELL":
        return "REMOVE";
      default:
        return "MAINTAIN";
    }
  }
}
