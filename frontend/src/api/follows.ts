import { apiDelete, apiGet, apiPost } from "./client";

// Mirrors backend/app/routers/follows.py — the RM-curated "My Topics" follow list
// behind the Change Radar tabs. Single-RM app: one global list. Matching of events
// to follows happens client-side (see ChangeRadar.matchesFollow); this API is CRUD.

export interface Follow {
  id: string;
  label: string;
  keyword: string;
  entity_key: string | null;
  entity_type: string | null;
  created_at: string;
}

export interface FollowsResponse {
  follows: Follow[];
  total: number;
}

export interface FollowCreate {
  label: string;
  keyword?: string;
  entity_key?: string | null;
  entity_type?: string | null;
}

export function getFollows(signal?: AbortSignal): Promise<FollowsResponse> {
  return apiGet<FollowsResponse>("/follows", signal);
}

// Idempotent on the normalised keyword — re-adding a topic returns the existing row.
export function addFollow(body: FollowCreate, signal?: AbortSignal): Promise<Follow> {
  return apiPost<Follow>("/follows", body, signal);
}

export function removeFollow(id: string, signal?: AbortSignal): Promise<void> {
  return apiDelete(`/follows/${id}`, signal);
}
