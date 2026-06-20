import { Request, Response } from "express";
import { PhoeniqsService } from "../services/phoeniqs.service";
import { SixService } from "../services/six.service";
import { NewsAIService } from "../services/newsai.service";
import { analysisRequestSchema } from "../../shared/schemas";
import { AnalysisResult, ApiResponse } from "../../shared/types";

export class AnalysisController {
  private phoeniqsService: PhoeniqsService;
  private sixService: SixService;
  private newsaiService: NewsAIService;

  constructor() {
    this.phoeniqsService = new PhoeniqsService();
    this.sixService = new SixService();
    this.newsaiService = new NewsAIService();
  }

  async analyzeStock(req: Request, res: Response): Promise<void> {
    try {
      const parsed = analysisRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        res.status(400).json({
          success: false,
          error: parsed.error.errors.map((e) => e.message).join(", "),
        });
        return;
      }

      const { symbol } = parsed.data;

      // SIX price and news are independent — fetch them concurrently.
      const [stockData, news] = await Promise.all([
        this.sixService.getStockPrice(symbol),
        this.newsaiService.getLatestNews(symbol, 5),
      ]);
      const sentiment = this.newsaiService.analyzeNewsSentiment(news);
      const recommendation = await this.phoeniqsService.analyzePortfolioRecommendation(
        symbol,
        stockData.currentPrice,
        sentiment.score,
        stockData,
        news
      );

      const response: ApiResponse<AnalysisResult> = {
        success: true,
        data: { stock: stockData, news, sentiment, recommendation },
      };
      res.json(response);
    } catch (error) {
      console.error("[Analysis] Error:", error);
      res.status(500).json({
        success: false,
        error: (error as Error).message || "Failed to analyze stock",
      });
    }
  }

  /**
   * Pings all three live integrations (SIX MCP, Event Registry, Phoeniqs) and
   * reports whether each is configured and reachable. Useful for verifying the
   * scaffolding end-to-end without running a full analysis.
   */
  async getIntegrationsStatus(_req: Request, res: Response): Promise<void> {
    try {
      const probes = await Promise.all([
        this.sixService.ping(),
        this.newsaiService.ping(),
        this.phoeniqsService.ping(),
      ]);

      res.json({ success: true, data: { probes } });
    } catch (error) {
      console.error("[Integrations] Error:", error);
      res.status(500).json({
        success: false,
        error: (error as Error).message || "Failed to check integrations",
      });
    }
  }
}
