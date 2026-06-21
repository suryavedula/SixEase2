import { apiGet, apiPatch, apiPost } from "./client";

export interface TaskItem {
  id: string;
  client_id: string | null;
  alert_id: string | null;
  title: string | null;
  source: string | null;
  execution_mode: string;
  status: string;
  result: Record<string, unknown> | null;
  created_at: string;
}

export interface TasksResponse {
  client_id: string;
  client_name: string;
  tasks: TaskItem[];
  total: number;
}

export interface TaskWithClient extends TaskItem {
  client_id: string;
  client_name: string;
}

export interface CreateTaskRequest {
  title: string;
  source: "note" | "promise";
  execution_mode?: "Auto" | "Manual";
}

export interface TaskTransitionRequest {
  status: "running" | "done" | "closed";
  result?: Record<string, unknown>;
}

export interface TaskRecommendation {
  security?: string;
  issuer?: string;
  isin?: string;
  valor?: string;
  industry_group?: string;
  region?: string;
  cio_view?: string;
  reason?: string;
}

export interface TaskBrief {
  summary: string | null;
  citations: { source: string; text: string }[];
  recommendations: TaskRecommendation[];
  provenance?: { notes_read?: number; articles_fetched?: number };
}

// Extract a presentation-ready brief from a task result. Handles BOTH the
// normalized shape (top-level summary/citations, written by the task runner) and
// the older nested per-agent shape (result.crm.{summary,citations}) so tasks that
// ran before normalization still render.
export function extractBrief(result: Record<string, unknown> | null | undefined): TaskBrief {
  const r = (result ?? {}) as Record<string, unknown>;
  const crm = (r.crm ?? {}) as Record<string, unknown>;

  const summary =
    (typeof r.summary === "string" && r.summary) ||
    (typeof crm.summary === "string" && crm.summary) ||
    null;

  const rawCites = (Array.isArray(r.citations) ? r.citations : crm.citations) ?? [];
  const citations = (Array.isArray(rawCites) ? rawCites : []).map((c) =>
    typeof c === "string"
      ? { source: c, text: "" }
      : { source: String((c as { source?: unknown })?.source ?? ""), text: String((c as { text?: unknown })?.text ?? "") },
  );

  const prov = (r.provenance ?? {
    notes_read: crm.notes_read,
    articles_fetched: crm.articles_fetched,
  }) as { notes_read?: number; articles_fetched?: number };

  const rawRecs = (Array.isArray(r.recommendations) ? r.recommendations : crm.recommendations) ?? [];
  const recommendations = (Array.isArray(rawRecs) ? rawRecs : []) as TaskRecommendation[];

  return { summary, citations, recommendations, provenance: prov };
}

export interface TaskDraftRef {
  kind: string;        // "reply" | "advisory"
  draft_id: string;
  summary?: string;
}

// Detect an email auto-draft "prepared answer" carried on a task result
// (Task(source="email", result={kind, draft_id, summary})). Returns null for
// ordinary research/portfolio briefs so the normal "Open brief" path is unaffected.
export function extractDraftRef(
  result: Record<string, unknown> | null | undefined,
): TaskDraftRef | null {
  if (!result) return null;
  const draftId = result.draft_id;
  const kind = result.kind;
  if (typeof draftId === "string" && (kind === "reply" || kind === "advisory")) {
    return {
      kind,
      draft_id: draftId,
      summary: typeof result.summary === "string" ? result.summary : undefined,
    };
  }
  return null;
}

export function getClientTasks(
  clientId: string,
  status?: string,
  signal?: AbortSignal,
): Promise<TasksResponse> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiGet<TasksResponse>(`/clients/${clientId}/tasks${qs}`, signal);
}

export function createTask(
  clientId: string,
  body: CreateTaskRequest,
  signal?: AbortSignal,
): Promise<TaskItem> {
  return apiPost<TaskItem>(`/clients/${clientId}/tasks`, body, signal);
}

export function patchTaskStatus(
  clientId: string,
  taskId: string,
  body: TaskTransitionRequest,
  signal?: AbortSignal,
): Promise<TaskItem> {
  return apiPatch<TaskItem>(`/clients/${clientId}/tasks/${taskId}`, body, signal);
}
