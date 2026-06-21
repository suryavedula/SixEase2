import { apiGet, API_BASE_URL } from "./client";

// Mirrors backend/app/routers/radar.py RadarResponse (TASK-059). The book-wide
// Change Radar: top changes ranked by aggregate impact, each fanned out to the
// clients it hits. Every figure is server-computed — the widget never invents one.

export interface ImpactedClient {
  client_id: string;
  client_name: string;
  exposure_chf: number | null;
  exposure_pct: number | null;
  drift_caused: number | null;
  dna_note: string | null;
  suggested_action: string | null;
  alert_id: string | null;
  swap_candidate: Record<string, unknown> | null;
}

export interface RadarEvent {
  id: string;
  action: string | null;
  entity_key: string | null;
  entity_type: string | null; // instrument | sector | client | macro
  entity_label: string | null;
  source: string | null; // news | cio | drift | dna | email
  event_ts: string | null;
  magnitude: number | null;
  impact_score: number | null;
  client_count: number;
  total_exposure_chf: number | null;
  impacted_clients: ImpactedClient[];
  suggested_batch_action: string | null;
  sources: unknown[] | null;
  unresolved_reason: string | null;
  news_url: string | null;
}

export interface RadarResponse {
  events: RadarEvent[];
  unresolved: RadarEvent[];
  total: number;
}

export function getRadar(limit = 10, signal?: AbortSignal): Promise<RadarResponse> {
  return apiGet<RadarResponse>(`/radar?limit=${limit}`, signal);
}

// A change pushed live over SSE by the dispatch loop (backend/app/radar_dispatch.py
// _event_payload). Compact by design — the client refetches getRadar() for detail.
export interface RadarStreamEvent {
  type: "change";
  id: string;
  entity_key: string | null;
  action: string | null;
  entity_label: string | null;
  source: string | null;
  magnitude: number | null;
  impact_score: number | null;
  client_count: number;
  total_exposure_chf: number | null;
}

// Open the proactive radar SSE stream. Returns the EventSource so the caller can
// close() it on unmount. The browser auto-reconnects on transient drops.
export function openRadarStream(
  onEvent: (event: RadarStreamEvent) => void,
): EventSource {
  const es = new EventSource(`${API_BASE_URL}/radar/stream`);
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as RadarStreamEvent);
    } catch {
      /* ignore keepalive / malformed frames */
    }
  };
  return es;
}
