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
