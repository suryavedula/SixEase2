import { ThemeToggle } from "../components/shell/ThemeToggle";
import { usePrefs, type DefaultView, type WidgetDensity } from "./PrefsProvider";

const DEFAULT_VIEW_OPTIONS: { value: DefaultView; label: string }[] = [
  { value: "holdings", label: "Holdings" },
  { value: "dna", label: "DNA" },
  { value: "portfolio", label: "Portfolio" },
  { value: "alerts", label: "Alerts" },
];

const DENSITY_OPTIONS: { value: WidgetDensity; label: string }[] = [
  { value: "narrative", label: "Narrative" },
  { value: "dense", label: "Dense" },
];

export function PrefsPanel() {
  const { prefs, setPref } = usePrefs();

  return (
    <div className="absolute right-0 top-full z-50 mt-2 w-64 rounded-xl border border-border bg-panel shadow-xl">
      <div className="border-b border-border px-4 py-2.5 text-[12px] font-semibold uppercase tracking-wider text-muted">
        Display Preferences
      </div>

      <div className="space-y-4 px-4 py-3">
        {/* Default View */}
        <div>
          <div className="mb-2 text-[12px] font-medium text-muted">Default View</div>
          <div className="grid grid-cols-2 gap-1.5">
            {DEFAULT_VIEW_OPTIONS.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                onClick={() => setPref("defaultView", value)}
                className={`rounded-lg border px-3 py-1.5 text-[12px] transition-colors ${
                  prefs.defaultView === value
                    ? "border-blue bg-blue/10 text-blue"
                    : "border-border bg-panel2 text-text hover:border-blue"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Density */}
        <div>
          <div className="mb-2 text-[12px] font-medium text-muted">Density</div>
          <div className="flex rounded-lg border border-border overflow-hidden">
            {DENSITY_OPTIONS.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                onClick={() => setPref("density", value)}
                className={`flex-1 py-1.5 text-[12px] transition-colors ${
                  prefs.density === value
                    ? "bg-blue/10 text-blue"
                    : "bg-panel2 text-muted hover:text-text"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Theme */}
        <div>
          <div className="mb-2 text-[12px] font-medium text-muted">Theme</div>
          <ThemeToggle />
        </div>
      </div>
    </div>
  );
}
