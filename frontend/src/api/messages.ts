import { apiGet, apiPatch, apiPost, API_BASE_URL } from "./client";

export interface ProvenanceEntry {
  fact_key: string;
  value: string;
  source: string;
}

export interface MessageDraft {
  id: string;
  client_id: string;
  channel: string | null;
  draft_text: string | null;
  fact_sheet: Record<string, unknown> | null;
  facts_used: string[] | null;
  provenance: ProvenanceEntry[] | null;
  style: string | null;
  status: string;
  created_at: string;
  updated_at: string | null;
}

export interface SendTestResponse {
  status: string;
  mailhog_ui: string;
}

export function getLatestDraft(
  clientId: string,
  signal?: AbortSignal,
): Promise<MessageDraft> {
  return apiGet<MessageDraft>(`/clients/${clientId}/drafts/latest`, signal);
}

export function getDraft(
  draftId: string,
  signal?: AbortSignal,
): Promise<MessageDraft> {
  return apiGet<MessageDraft>(`/drafts/${draftId}`, signal);
}

export function patchDraftText(
  draftId: string,
  draft_text: string,
  signal?: AbortSignal,
): Promise<MessageDraft> {
  return apiPatch<MessageDraft>(`/drafts/${draftId}`, { draft_text }, signal);
}

export function approveDraft(
  draftId: string,
  signal?: AbortSignal,
): Promise<{ id: string; status: string }> {
  return apiPost<{ id: string; status: string }>(
    `/drafts/${draftId}/approve`,
    {},
    signal,
  );
}

export async function triggerRender(
  draftId: string,
  preset: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const url = `${API_BASE_URL}/admin/render/message?draft_id=${encodeURIComponent(draftId)}&preset=${encodeURIComponent(preset)}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!res.ok) {
    throw new Error(`POST /admin/render/message → ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export function sendTestDraft(
  draftId: string,
  signal?: AbortSignal,
): Promise<SendTestResponse> {
  return apiPost<SendTestResponse>(`/drafts/${draftId}/send-test`, {}, signal);
}
