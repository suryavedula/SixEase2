// Microsoft Graph delegated sign-in (TASK-061).
// The RM signs in with their Microsoft account so the app can read/send through
// the shared mailbox on their behalf. Sign-in is a full-page redirect dance driven
// by the backend (/auth/ms/login → Microsoft → /auth/ms/callback → back here).

import { API_BASE_URL, apiGet, apiPost } from "./client";

export interface AuthStatus {
  signed_in: boolean;
  username?: string | null;
  name?: string | null;
}

export function getAuthStatus(signal?: AbortSignal): Promise<AuthStatus> {
  return apiGet<AuthStatus>("/auth/ms/status", signal);
}

// Full-page navigation: the backend 307-redirects to Microsoft, then back to the SPA
// with ?signin=ok or ?signin_error=... appended.
export function startMicrosoftLogin(): void {
  window.location.href = `${API_BASE_URL}/auth/ms/login`;
}

export function signOut(signal?: AbortSignal): Promise<AuthStatus> {
  return apiPost<AuthStatus>("/auth/ms/logout", {}, signal);
}
