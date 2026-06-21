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
  // Backend declares str but actually stores the style-profile object ({preset, …}).
  style: string | Record<string, unknown> | null;
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
  preset?: string,
  signal?: AbortSignal,
): Promise<unknown> {
  // No preset → the backend renders in the client's own style profile.
  let url = `${API_BASE_URL}/admin/render/message?draft_id=${encodeURIComponent(draftId)}`;
  if (preset) url += `&preset=${encodeURIComponent(preset)}`;
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

interface AssembleResult {
  draft_id: string;
  client_id: string;
  fact_sheet: Record<string, unknown>;
  has_proposal: boolean;
}

// Deterministically assemble the fact sheet for a client/alert — creates the
// MessageDraft row (no LLM). Returns the new draft id.
async function assembleFactSheet(
  clientId: string,
  alertId?: string | null,
  signal?: AbortSignal,
): Promise<AssembleResult> {
  const params = new URLSearchParams({ client_id: clientId });
  if (alertId) params.set("alert_id", alertId);
  const url = `${API_BASE_URL}/admin/assemble/fact-sheet?${params.toString()}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!res.ok) {
    // FastAPI puts the real reason in {detail}; surface it instead of a bare code.
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new Error(detail);
  }
  const body = (await res.json()) as { status: string; loaded: AssembleResult };
  return body.loaded;
}

// Full draft generation: assemble the fact sheet (deterministic), then render it
// into prose via the LLM in the client's style profile. Returns the ready draft.
export async function generateDraft(
  clientId: string,
  alertId?: string | null,
  signal?: AbortSignal,
): Promise<MessageDraft> {
  const { draft_id } = await assembleFactSheet(clientId, alertId, signal);
  await triggerRender(draft_id, undefined, signal);
  return getDraft(draft_id, signal);
}

export function sendTestDraft(
  draftId: string,
  signal?: AbortSignal,
): Promise<SendTestResponse> {
  return apiPost<SendTestResponse>(`/drafts/${draftId}/send-test`, {}, signal);
}
