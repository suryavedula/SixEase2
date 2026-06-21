// Per-tile size hint driving the bento grid span (TASK-066/067). Authored
// shape (`WidgetSpec`) keeps `size` optional so the backend/InputDock need not
// emit it; `CanvasTileSpec` is the resolved runtime shape held in AppShell state.
export type TileSize = "standard" | "wide" | "tall";

export interface WidgetSpec {
  component: string;
  props: Record<string, unknown>;
  size?: TileSize;
}

// Runtime spec: a stable id (for pin/close/collapse keyed off identity, not
// array index) plus a resolved size and per-tile chrome flags. `rail` set means
// the RM has pinned the tile to the (left) Action Center rail (TASK-070).
export interface CanvasTileSpec extends WidgetSpec {
  id: string;
  size: TileSize;
  collapsed?: boolean;
  rail?: "left";
}
