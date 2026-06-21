import { useState } from "react";
import { Settings } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { BackendStatus } from "./BackendStatus";
import { MicrosoftSignIn } from "./MicrosoftSignIn";
import { PrefsPanel } from "../../prefs/PrefsPanel";

// App header (TASK-003, TASK-066): logo + brand on the left; backend status,
// avatar, prefs and theme toggle on the right. Alerts live solely in the Action
// Center rail. Sticky + blurred, matching the mock's .app-hd (Project-Overview.html).

export function Header() {
  const [prefsOpen, setPrefsOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 flex items-center gap-3 border-b border-border bg-[var(--header-bg)] px-4 py-2.5 backdrop-blur-md">
      {/* Brand */}
      <div className="flex items-center gap-2.5">
        <div className="flex h-[26px] w-[26px] items-center justify-center rounded-lg bg-blue text-sm text-white">
          ◆
        </div>
        <div className="leading-tight">
          <div className="text-[14px] font-semibold">
            SixEase
          </div>
          <div className="text-[11px] text-muted">
            Relationship intelligence for the RM
          </div>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2.5">
        <BackendStatus />

        {/* Microsoft sign-in (delegated Graph) — RM avatar when signed in. */}
        <MicrosoftSignIn />

        {/* Prefs gear */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setPrefsOpen((o) => !o)}
            title="Display preferences"
            aria-label="Display preferences"
            aria-expanded={prefsOpen}
            className={`flex h-9 w-9 items-center justify-center rounded-[10px] border border-border bg-panel2 text-text transition-colors hover:border-blue ${prefsOpen ? "border-blue text-blue" : ""}`}
          >
            <Settings size={18} strokeWidth={1.75} />
          </button>
          {prefsOpen && <PrefsPanel />}
        </div>

        <ThemeToggle />
      </div>
    </header>
  );
}
