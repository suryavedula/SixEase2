import { z } from "zod";

export const analysisRequestSchema = z.object({
  // Accepts a ticker (e.g. TSLA) or a company name (e.g. "Credit Suisse") —
  // SIX find_instrument resolves both. Trimmed; length bounded to stay sane.
  symbol: z.string().trim().min(1).max(64),
  days: z.number().int().min(1).max(90).optional().default(7),
});

export type ValidatedAnalysisRequest = z.infer<typeof analysisRequestSchema>;
