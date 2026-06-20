export interface StockData {
  symbol: string;
  name: string;
  currentPrice: number;
  currency: string;
  change: number;
  changePercent: number;
  timestamp: string;
}

export interface NewsArticle {
  id: string;
  title: string;
  summary: string;
  url: string;
  source: string;
  publishedAt: string;
  sentiment?: SentimentAnalysis;
}

export interface SentimentAnalysis {
  score: number;
  magnitude: number;
  label: "BEARISH" | "NEUTRAL" | "BULLISH";
  confidence: number;
}

export interface PortfolioRecommendation {
  symbol: string;
  currentPrice: number;
  recommendation: "BUY" | "HOLD" | "SELL";
  confidence: number;
  reasoning: string;
  suggestedAction: "ADD" | "REMOVE" | "MAINTAIN";
  targetPrice?: number;
  stopLoss?: number;
}

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

/** A captured request/response round-trip for one integration, for the status UI. */
export interface IntegrationProbe {
  name: string;
  configured: boolean;
  ok: boolean;
  durationMs: number;
  request: {
    method: string;
    url: string;
    headers?: Record<string, string>;
    body?: unknown;
  };
  response?: {
    status?: number;
    body: string;
  };
  error?: string;
}

export interface AnalysisRequest {
  symbol: string;
  days?: number;
}

export interface AnalysisResult {
  stock: StockData;
  news: NewsArticle[];
  sentiment: SentimentAnalysis;
  recommendation: PortfolioRecommendation;
}
