import { apiGet } from "./client";

// ---------------------------------------------------------------------------
// /portfolio/fit
// ---------------------------------------------------------------------------

export interface ConflictItem {
  tag: string;
  impact: string;
  direction: number;
}

export interface HoldingFit {
  position_id: string;
  issuer: string | null;
  security: string | null;
  industry_group: string | null;
  sub_asset_class: string | null;
  valor: string | null;
  current_chf: number | null;
  tags: Record<string, unknown> | null;
  fit_score: number | null;
  conflicts: ConflictItem[] | null;
  cio_view: string | null;
}

export interface PortfolioFitResponse {
  client_id: string;
  client_name: string;
  mandate: string;
  portfolio_fit: number | null;
  holdings: HoldingFit[];
  total_holdings: number;
  scored_holdings: number;
}

// ---------------------------------------------------------------------------
// /portfolio/allocation
// ---------------------------------------------------------------------------

export interface SACRow {
  sub_asset_class: string;
  current_chf: number;
  current_pct: number;
  target_pct: number;
  drift_pp: number;
  breach: boolean;
}

export interface AllocationResponse {
  client_id: string;
  client_name: string;
  mandate: string;
  total_chf: number;
  sac_rows: SACRow[];
}

// ---------------------------------------------------------------------------
// /portfolio/swaps
// ---------------------------------------------------------------------------

export interface SwapCandidate {
  candidate_isin: string | null;
  candidate_valor: string | null;
  candidate_issuer: string | null;
  candidate_security: string | null;
  candidate_cio_view: string | null;
  fit_gain: number | null;
  dna_reason: string | null;
  mandate_neutral: boolean;
  sources: unknown[] | null;
}

export interface PositionSwaps {
  position_id: string;
  issuer: string | null;
  security: string | null;
  industry_group: string | null;
  sub_asset_class: string | null;
  current_chf: number | null;
  current_fit_score: number | null;
  conflict_tags: unknown[] | null;
  candidates: SwapCandidate[];
}

export interface KeptPosition {
  position_id: string;
  issuer: string | null;
  security: string | null;
  industry_group: string | null;
  sub_asset_class: string | null;
  current_chf: number | null;
  current_fit_score: number | null;
  conflict_tags: unknown[] | null;
  keep_reason: string | null;
}

export interface SwapProposalsResponse {
  client_id: string;
  client_name: string;
  mandate: string;
  conflict_positions: number;
  total_proposals: number;
  positions: PositionSwaps[];
  kept_positions: KeptPosition[];
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

export function getPortfolioFit(
  clientId: string,
  signal?: AbortSignal,
): Promise<PortfolioFitResponse> {
  return apiGet<PortfolioFitResponse>(`/clients/${clientId}/portfolio/fit`, signal);
}

export function getPortfolioAllocation(
  clientId: string,
  signal?: AbortSignal,
): Promise<AllocationResponse> {
  return apiGet<AllocationResponse>(`/clients/${clientId}/portfolio/allocation`, signal);
}

export function getPortfolioSwaps(
  clientId: string,
  signal?: AbortSignal,
): Promise<SwapProposalsResponse> {
  return apiGet<SwapProposalsResponse>(`/clients/${clientId}/portfolio/swaps`, signal);
}
