import { useEffect, useState } from "react";
import { LogIn, LogOut } from "lucide-react";
import { getAuthStatus, signOut, startMicrosoftLogin, type AuthStatus } from "../../api/auth";

// Header sign-in control (TASK-061). Signed out → "Sign in with Microsoft" button.
// Signed in → RM initials avatar + sign-out. Polls /auth/ms/status on mount; the
// backend callback bounces back here with ?signin=ok, which triggers a re-check.

function initialsOf(label: string): string {
  return (
    label
      .split(/[\s@.]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0]?.toUpperCase() ?? "")
      .join("") || "RM"
  );
}

export function MicrosoftSignIn() {
  const [status, setStatus] = useState<AuthStatus | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getAuthStatus(ctrl.signal)
      .then(setStatus)
      .catch(() => setStatus({ signed_in: false }));

    // Clean the ?signin=ok / ?signin_error=... flag the callback appended.
    const params = new URLSearchParams(window.location.search);
    if (params.has("signin") || params.has("signin_error")) {
      params.delete("signin");
      params.delete("signin_error");
      const qs = params.toString();
      window.history.replaceState(
        {},
        "",
        window.location.pathname + (qs ? `?${qs}` : ""),
      );
    }
    return () => ctrl.abort();
  }, []);

  if (status?.signed_in) {
    const label = status.name || status.username || "Signed in";
    return (
      <div className="flex items-center gap-2">
        <div
          title={label}
          className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-blue text-[11px] font-semibold text-white"
        >
          {initialsOf(status.name || status.username || "RM")}
        </div>
        <button
          type="button"
          onClick={() => signOut().then(setStatus).catch(() => setStatus({ signed_in: false }))}
          title={`Sign out ${label}`}
          aria-label="Sign out"
          className="flex h-9 w-9 items-center justify-center rounded-[10px] border border-border bg-panel2 text-text transition-colors hover:border-blue"
        >
          <LogOut size={16} strokeWidth={1.75} />
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={startMicrosoftLogin}
      className="flex items-center gap-2 rounded-[10px] border border-border bg-panel2 px-3 py-1.5 text-[12px] font-medium text-text transition-colors hover:border-blue"
    >
      <LogIn size={15} strokeWidth={1.75} />
      Sign in with Microsoft
    </button>
  );
}
