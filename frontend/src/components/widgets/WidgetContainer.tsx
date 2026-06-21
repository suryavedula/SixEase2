import type { ReactNode } from "react";
import { ShieldAlert } from "lucide-react";
import { cn } from "../../lib/utils";
import { usePrefs } from "../../prefs/PrefsProvider";

// Ported from Kielis_Advisor_workbech (WidgetContainer), re-tokenised onto our
// theme variables (bg-panel / border-border / text-*) so the light/dark toggle
// keeps working. The titled panel + "source" provenance badge is the shared
// chrome for the ported generative-UI widgets.

interface WidgetContainerProps {
  title: string;
  source?: string;
  children: ReactNode;
  className?: string;
  badges?: ReactNode;
}

export function WidgetContainer({ title, source, children, className, badges }: WidgetContainerProps) {
  const { prefs } = usePrefs();
  const dense = prefs.density === "dense";
  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-2xl border border-border bg-panel shadow-sm",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center justify-between border-b border-border bg-panel2",
          dense ? "px-3 py-2" : "px-4 py-3",
        )}
      >
        <div className="flex items-center gap-2">
          <h3 className="text-[13px] font-semibold tracking-wide text-text">{title}</h3>
          {badges}
        </div>
        {source && (
          <div className="flex items-center gap-1.5 rounded-full bg-panel3 px-2 py-0.5 text-[10px] font-medium text-muted">
            <ShieldAlert className="h-3 w-3" />
            <span>{source}</span>
          </div>
        )}
      </div>
      <div className={cn("flex-1 overflow-y-auto", dense ? "p-3" : "p-4")}>{children}</div>
    </div>
  );
}
