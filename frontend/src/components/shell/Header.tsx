import { useState } from "react";
import { ThemeToggle } from "./ThemeToggle";
import { BackendStatus } from "./BackendStatus";
import { PrefsPanel } from "../../prefs/PrefsPanel";

// App header (TASK-003): logo + brand on the left; backend status, bell (toggles
// the Action Center), avatar and theme toggle on the right. Sticky + blurred,
// matching the mock's .app-hd (Project-Overview.html).

interface HeaderProps {
  alertCount: number;
  onToggleActionCenter: () => void;
}

export function Header({ alertCount, onToggleActionCenter }: HeaderProps) {
  const [prefsOpen, setPrefsOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 flex items-center gap-3 border-b border-border bg-[var(--header-bg)] px-4 py-2.5 backdrop-blur-md">
      {/* Brand */}
      <div className="flex items-center gap-2.5">
        <div className="flex h-[26px] w-[26px] items-center justify-center rounded-lg bg-gradient-to-br from-blue to-purple text-sm text-white">
          ◆
        </div>
        <div className="leading-tight">
          <div className="text-[14px] font-semibold">
            Wealth Advisor Workbench
          </div>
          <div className="text-[11px] text-muted">
            Relationship intelligence for the RM
          </div>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2.5">
        <BackendStatus />

        {/* Bell → Action Center */}
        <button
          type="button"
          onClick={onToggleActionCenter}
          title="Toggle Action Center"
          aria-label={`Action Center, ${alertCount} alerts`}
          className="relative flex h-9 w-9 items-center justify-center rounded-[10px] border border-border bg-panel2 text-text transition-colors hover:border-blue"
        >
          🔔
          {alertCount > 0 && (
            <span className="absolute -right-1.5 -top-1.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red px-1 text-[10px] font-semibold text-white">
              {alertCount}
            </span>
          )}
        </button>

        {/* Avatar (RM initials — placeholder until auth lands) */}
        <div className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-gradient-to-br from-teal to-blue text-[11px] font-semibold text-white">
          SM
        </div>

        {/* Prefs gear */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setPrefsOpen((o) => !o)}
            title="Display preferences"
            aria-label="Display preferences"
            aria-expanded={prefsOpen}
            className={`flex h-9 w-9 items-center justify-center rounded-[10px] border border-border bg-panel2 text-text transition-colors hover:border-blue ${prefsOpen ? "border-blue" : ""}`}
          >
            ⚙️
          </button>
          {prefsOpen && <PrefsPanel />}
        </div>

        <ThemeToggle />
      </div>
    </header>
  );
}
