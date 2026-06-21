// API client base (TASK-003, EPIC-01).
// Base URL comes from VITE_API_BASE_URL (see .env). When unset it falls back to
// same-origin (relative) requests rather than a hardcoded dev port.

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!res.ok) {
    throw new Error(`GET ${path} → ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export async function apiPatch<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    throw new Error(`PATCH ${path} → ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    throw new Error(`POST ${path} → ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

// DELETE returns no body (204) on success — resolves void, throws on non-2xx.
export async function apiDelete(path: string, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!res.ok) {
    throw new Error(`DELETE ${path} → ${res.status} ${res.statusText}`);
  }
}
