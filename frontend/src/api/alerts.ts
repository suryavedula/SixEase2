import { apiGet, apiPatch, apiPost } from "./client";

export interface AlertItem {
  id: string;
  alert_class: string | null;
  action_type: string;
  severity: string;
  trigger: string | null;
  why: string | null;
  suggested_action: string | null;
  status: string;
  confidence: number | null;
  rank_score: number | null;
  evidence: unknown[] | null;
  created_at: string;
  snoozed_until?: string | null;
  dismissed_reason?: string | null;
}

export interface AlertsResponse {
  client_id: string;
  client_name: string;
  alerts: AlertItem[];
  total: number;
}

export interface AlertWithClient extends AlertItem {
  client_id: string;
  client_name: string;
}

export interface AlertTransitionRequest {
  status: "acted" | "dismissed" | "snoozed";
  snoozed_until?: string;   // ISO-8601; required when status="snoozed"
  dismissed_reason?: string;
}

export interface ConvertResponse {
  alert_id: string;
  task_id: string;
}

export function getClientAlerts(
  clientId: string,
  status?: string,
  signal?: AbortSignal,
): Promise<AlertsResponse> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiGet<AlertsResponse>(`/clients/${clientId}/alerts${qs}`, signal);
}

export function patchAlertStatus(
  clientId: string,
  alertId: string,
  body: AlertTransitionRequest,
  signal?: AbortSignal,
): Promise<AlertItem> {
  return apiPatch<AlertItem>(`/clients/${clientId}/alerts/${alertId}`, body, signal);
}

export function convertAlertToTask(
  clientId: string,
  alertId: string,
  signal?: AbortSignal,
): Promise<ConvertResponse> {
  return apiPost<ConvertResponse>(`/clients/${clientId}/alerts/${alertId}/convert`, {}, signal);
}
