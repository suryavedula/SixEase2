import type { ReactNode } from "react";
import {
  ArrowLeftToLine,
  ChevronDown,
  ChevronUp,
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";
import type { CanvasTileSpec } from "../../registry/types";
import { SPAN_CLASS, SELF_CONTAINED } from "../../registry/tileLayout";
import { cn } from "../../lib/utils";
import { usePrefs } from "../../prefs/PrefsProvider";

// Per-tile bento cell + chrome (TASK-066/069). The chrome is an absolutely-
// positioned overlay revealed on hover, so it works uniformly over every widget
// without editing any of them. The body pads bare widgets (a plain title + inner
// blocks) so their content doesn't sit flush against the tile edge and read as if
// it's overlapping the neighbouring tile; SELF_CONTAINED widgets already own a
// padded card that fills the tile, so they're left unpadded to avoid a double inset.

interface CanvasTileProps {
  tile: CanvasTileSpec;
  maximized: boolean;
  // True for a freshly-inserted tile: adds a brief highlight ring that fades via
  // the tile's `transition-shadow` once the flag clears (TASK-067).
  isNew: boolean;
  onToggleCollapse: (id: string) => void;
  onToggleMaximize: (id: string) => void;
  // Pin the tile to the left rail, or unpin (null). Re-clicking pin unpins.
  onSetRail: (id: string, rail: "left" | null) => void;
  onClose: (id: string) => void;
  children: ReactNode;
}

const ICON = "h-3.5 w-3.5";
const BTN =
  "flex h-6 w-6 items-center justify-center rounded-md text-dim transition-colors hover:bg-panel3 hover:text-text";

export function CanvasTile({
  tile,
  maximized,
  isNew,
  onToggleCollapse,
  onToggleMaximize,
  onSetRail,
  onClose,
  children,
}: CanvasTileProps) {
  const { prefs } = usePrefs();
  const selfContained = SELF_CONTAINED.has(tile.component);
  return (
    <div
      className={cn(
        "group relative flex min-h-0 min-w-0 flex-col rounded-2xl border border-border bg-panel transition-shadow",
        // Entrance: tiles mount only when inserted, so this plays once per insert.
        "motion-safe:animate-tile-enter",
        maximized
          ? "absolute inset-0 z-40 shadow-2xl"
          : SPAN_CLASS[tile.size],
        // Pinned ring takes precedence; otherwise a transient insert highlight.
        tile.rail
          ? "ring-1 ring-blue/40"
          : isNew && "ring-2 ring-blue/50",
      )}
    >
      {/* Overlay chrome — top-right, reveals on hover (or while pinned/maximized) */}
      <div
        className={cn(
          "absolute right-2 top-2 z-10 flex items-center gap-0.5 rounded-lg border border-border bg-panel2/90 px-0.5 py-0.5 opacity-0 shadow-sm backdrop-blur-sm transition-opacity group-hover:opacity-100 focus-within:opacity-100",
          (tile.rail || maximized) && "opacity-100",
        )}
      >
        <button
          type="button"
          className={BTN}
          title={tile.collapsed ? "Expand" : "Collapse"}
          aria-label={tile.collapsed ? "Expand tile" : "Collapse tile"}
          onClick={() => onToggleCollapse(tile.id)}
        >
          {tile.collapsed ? (
            <ChevronDown className={ICON} />
          ) : (
            <ChevronUp className={ICON} />
          )}
        </button>
        <button
          type="button"
          className={BTN}
          title={maximized ? "Restore" : "Maximize"}
          aria-label={maximized ? "Restore tile" : "Maximize tile"}
          onClick={() => onToggleMaximize(tile.id)}
        >
          {maximized ? (
            <Minimize2 className={ICON} />
          ) : (
            <Maximize2 className={ICON} />
          )}
        </button>
        <button
          type="button"
          className={cn(BTN, tile.rail === "left" && "text-blue hover:text-blue")}
          title={
            tile.rail === "left"
              ? "Unpin from rail"
              : "Pin to rail — keep this view in the sidebar"
          }
          aria-label={tile.rail === "left" ? "Unpin from rail" : "Pin to rail"}
          aria-pressed={tile.rail === "left"}
          onClick={() => onSetRail(tile.id, tile.rail === "left" ? null : "left")}
        >
          <ArrowLeftToLine className={ICON} />
        </button>
        <button
          type="button"
          className={cn(BTN, "hover:text-red")}
          title="Close"
          aria-label="Close tile"
          onClick={() => onClose(tile.id)}
        >
          <X className={ICON} />
        </button>
      </div>

      {/* Body — hidden when collapsed (clamp to a thin header strip). */}
      {tile.collapsed ? (
        <div className="h-10" aria-hidden />
      ) : (
        <div
          className={cn(
            "flex-1 overflow-auto",
            !selfContained && (prefs.density === "dense" ? "p-3" : "p-4"),
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}
