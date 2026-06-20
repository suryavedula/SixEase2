import { apiGet } from "./client";

export interface BookSwapSummary {
  position_id: string;
  from_security: string | null;
  to_security: string | null;
  fit_gain: number | null;
  dna_reason: string | null;
}

export interface BookClient {
  client_id: string;
  client_name: string;
  mandate: string;
  portfolio_fit: number | null;
  total_positions: number;
  conflict_positions: number;
  proposal_count: number;
  kept_count: number;
  top_swaps: BookSwapSummary[];
}

export interface BookResponse {
  total_clients: number;
  scored_clients: number;
  clients: BookClient[];
}

export function getBook(mandate?: string, signal?: AbortSignal): Promise<BookResponse> {
  const qs = mandate ? `?mandate=${encodeURIComponent(mandate)}` : "";
  return apiGet<BookResponse>(`/book${qs}`, signal);
}
