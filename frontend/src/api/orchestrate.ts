import { apiPost } from "./client";
import type { WidgetSpec } from "../registry/types";

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface OrchestrateRequest {
  query: string;
  client_id?: string | null;
  history?: ChatTurn[];
}

export interface OrchestrateResponse {
  reply: string;
  specs: WidgetSpec[];
  client_id?: string | null;
  client_name?: string | null;
}

export function postOrchestrate(
  body: OrchestrateRequest,
  signal?: AbortSignal,
): Promise<OrchestrateResponse> {
  return apiPost<OrchestrateResponse>("/orchestrate", body, signal);
}
