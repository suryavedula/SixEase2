import { apiGet } from "./client";

// Backend health client (TASK-003, AC #3: talks to backend /health).
// Mirrors the TASK-002 contract: GET /health → { status, service, environment }.

export interface HealthResponse {
  status: string;
  service: string;
  environment: string;
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/health", signal);
}
