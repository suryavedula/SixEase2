import { apiGet } from "./client";

export interface DnaSource {
  id: string;
  date: string | null;
  medium: string | null;
  note: string | null;
}

export interface DnaItem {
  text: string;
  tag: string | null;
  source_note_ids: string[];
  confidence: number;
}

export interface DnaResponse {
  id: string;
  client_id: string;
  client_name: string;
  mandate: string | null;
  version: number;
  values: DnaItem[] | null;
  exclusions: DnaItem[] | null;
  tilts: DnaItem[] | null;
  life_events: DnaItem[] | null;
  promises: DnaItem[] | null;
  style_profile: Record<string, unknown> | null;
  business_context: string | null;
  family_context: string | null;
  temperament: string | null;
  sources: DnaSource[];
  created_at: string;
  updated_at: string;
}

export function getClientDna(clientId: string, signal?: AbortSignal): Promise<DnaResponse> {
  return apiGet<DnaResponse>(`/clients/${clientId}/dna`, signal);
}
