import axios, { AxiosInstance } from "axios";
import { IntegrationProbe, NewsArticle, SentimentAnalysis } from "../../shared/types";
import { maskValue, preview } from "./probe";

// News + sentiment come from the Event Registry API (newsapi.ai), the feed
// behind the Tenity MCP-News server. The endpoint is JSON-RPC-free REST: a
// POST to /article/getArticles with the apiKey in the body. See challenge README.
const DEFAULT_NEWSAI_URL = "https://eventregistry.org/api/v1";

interface EventRegistryArticle {
  uri?: string | number;
  title?: string;
  body?: string;
  url?: string;
  dateTime?: string;
  dateTimePub?: string;
  sentiment?: number | null;
  source?: { title?: string };
}

export class NewsAIService {
  private client: AxiosInstance;
  private apiKey: string;
  private readonly baseUrl: string;
  readonly configured: boolean;

  constructor() {
    this.apiKey = process.env.NEWSAPI_KEY || process.env.NEWSAI_API_KEY || "";
    this.baseUrl = process.env.NEWSAI_API_URL || DEFAULT_NEWSAI_URL;
    this.configured = Boolean(this.apiKey) && !this.apiKey.startsWith("your_");

    if (!this.configured) {
      console.warn("[NewsAI] API key not configured; set NEWSAPI_KEY");
    }

    this.client = axios.create({
      baseURL: this.baseUrl,
      headers: { "Content-Type": "application/json" },
      timeout: 15000,
    });
  }

  async getLatestNews(query: string, limit = 10): Promise<NewsArticle[]> {
    if (!this.configured) {
      throw new Error("[NewsAI] not configured: set NEWSAPI_KEY");
    }

    const { data } = await this.client.post("/article/getArticles", {
      apiKey: this.apiKey,
      keyword: query,
      keywordOper: "and",
      lang: "eng",
      articlesCount: limit,
      articlesSortBy: "date",
      resultType: "articles",
      dataType: ["news"],
      includeArticleSentiment: true,
    });

    if (data?.error) throw new Error(`[NewsAI] ${data.error}`);

    const results: EventRegistryArticle[] = data?.articles?.results || [];

    return results.map((a, i): NewsArticle => {
      const title = a.title || "";
      const summary = (a.body || "").slice(0, 280).trim();
      return {
        id: String(a.uri ?? `news-${i}`),
        title,
        summary,
        url: a.url || "#",
        source: a.source?.title || "Unknown",
        publishedAt: a.dateTimePub || a.dateTime || new Date().toISOString(),
        // Event Registry returns its own sentiment in [-1, 1] when available;
        // otherwise fall back to the local keyword heuristic.
        sentiment:
          typeof a.sentiment === "number"
            ? this.fromScore(a.sentiment)
            : this.analyzeSentiment(`${title} ${summary}`),
      };
    });
  }

  analyzeNewsSentiment(news: NewsArticle[]): SentimentAnalysis {
    if (news.length === 0) {
      return { score: 0, magnitude: 0, label: "NEUTRAL", confidence: 0 };
    }
    const scored = news.filter((n) => n.sentiment);
    if (scored.length > 0) {
      const avg = scored.reduce((sum, n) => sum + (n.sentiment?.score || 0), 0) / scored.length;
      return this.fromScore(avg);
    }
    const text = news.map((n) => `${n.title} ${n.summary}`).join(" ");
    return this.analyzeSentiment(text);
  }

  /** Liveness check that captures the full request/response for the status UI. */
  async ping(): Promise<IntegrationProbe> {
    const started = Date.now();
    const realBody = {
      apiKey: this.apiKey,
      keyword: "markets",
      articlesCount: 1,
      resultType: "articles",
      dataType: ["news"],
    };
    const request = {
      method: "POST",
      url: `${this.baseUrl}/article/getArticles`,
      // Show the apiKey masked in the displayed request.
      body: { ...realBody, apiKey: maskValue(this.apiKey) },
    };

    if (!this.configured) {
      return {
        name: "Event Registry (newsapi.ai)",
        configured: false,
        ok: false,
        durationMs: 0,
        request,
        error: "NEWSAPI_KEY not set",
      };
    }

    try {
      const res = await this.client.post("/article/getArticles", realBody);
      const apiError = res.data?.error;
      return {
        name: "Event Registry (newsapi.ai)",
        configured: true,
        ok: !apiError,
        durationMs: Date.now() - started,
        request,
        response: { status: res.status, body: preview(res.data) },
        error: apiError ? String(apiError) : undefined,
      };
    } catch (error) {
      const ax = error as { response?: { status?: number; data?: unknown } };
      return {
        name: "Event Registry (newsapi.ai)",
        configured: true,
        ok: false,
        durationMs: Date.now() - started,
        request,
        response: ax.response ? { status: ax.response.status, body: preview(ax.response.data) } : undefined,
        error: (error as Error).message,
      };
    }
  }

  /** Map an Event Registry sentiment score in [-1, 1] to our label model. */
  private fromScore(score: number): SentimentAnalysis {
    let label: SentimentAnalysis["label"] = "NEUTRAL";
    if (score > 0.2) label = "BULLISH";
    else if (score < -0.2) label = "BEARISH";
    return {
      score: parseFloat(score.toFixed(3)),
      magnitude: parseFloat(Math.abs(score).toFixed(3)),
      label,
      confidence: parseFloat(Math.min(0.85, Math.abs(score) * 2).toFixed(3)),
    };
  }

  private analyzeSentiment(text: string): SentimentAnalysis {
    const positiveWords = ["bullish", "buy", "strong", "growth", "positive", "outperform", "upgrade", "surge", "rally", "record"];
    const negativeWords = ["bearish", "sell", "weak", "decline", "negative", "underperform", "downgrade", "drop", "crash", "loss"];

    const words = text.toLowerCase().split(/\W+/);
    let positiveCount = 0;
    let negativeCount = 0;

    for (const word of words) {
      if (positiveWords.includes(word)) positiveCount++;
      if (negativeWords.includes(word)) negativeCount++;
    }

    const total = positiveCount + negativeCount || 1;
    const score = (positiveCount - negativeCount) / total;
    return this.fromScore(score);
  }
}
