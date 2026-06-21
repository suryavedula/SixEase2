// Bento layout policy (TASK-066/067). Maps each registered widget to a default
// tile size and each size to its grid-span classes. This is the single knob for
// "make the canvas read right" — no backend change needed; a spec may still
// override with an explicit `size`.
import type { TileSize, WidgetSpec } from "./types";

// Heavy dashboards / text panels go wide; vertical lists go tall; charts/cards
// stay standard. Anything unlisted falls back to "standard".
export const DEFAULT_SIZE: Record<string, TileSize> = {
  // Conversational — rendered bare (see Canvas BARE set), listed for completeness.
  ChatMessage: "wide",
  // Wide: multi-column dashboards & text-heavy panels.
  Client360: "wide",
  PortfolioView: "wide",
  BeforeAfter: "wide",
  ClientBook: "wide",
  ChangeRadar: "wide",
  MeetingPrep: "wide",
  EmailDraft: "wide",
  Research: "wide",
  // Tall: vertical lists / timelines.
  RelationshipTimeline: "tall",
  ConflictsList: "tall",
  TasksList: "tall",
  // Standard: charts / cards.
  DnaCard: "standard",
  DnaRadar: "standard",
  AllocationDonut: "standard",
  DriftBars: "standard",
  FitHeatmap: "standard",
  SectorTreemap: "standard",
  VoiceNoteWidget: "standard",
  SourcesFooter: "standard",
};

// Grid span for the bento (TASK-067). The Canvas is a CSS grid whose column
// count adapts to the *canvas* width via container queries (1 / 2 / 3 cols, see
// Canvas.tsx) — never the viewport, so spans stay correct as the side rails open
// and close. Spans are layout intent, not pixels (grounding rule).
// - `standard`: a single 1×1 cell.
// - `wide`: spans the FULL row (`col-span-full`) at every column count. Heavy
//   dashboards (ChangeRadar, Client360, PortfolioView, …) thus use the whole
//   canvas width instead of leaving an empty trailing column on the right when
//   shown alone — the previous `@3xl:col-span-2` reserved a 3rd column that sat
//   empty whenever no neighbour landed beside it. Charts (`standard`) still pack
//   3-up below for density.
// - `tall`: spans 2 rows so vertical lists/timelines get room and the masonry
//   packs around them. Span classes are enumerated as full static strings so the
//   Tailwind v4 JIT keeps them.
export const SPAN_CLASS: Record<TileSize, string> = {
  standard: "",
  wide: "col-span-full",
  tall: "row-span-2",
};

export function resolveSize(spec: WidgetSpec): TileSize {
  return spec.size ?? DEFAULT_SIZE[spec.component] ?? "standard";
}

// Widgets that render their OWN card surface(s) — either a single WidgetContainer
// that fills the tile (ChangeRadar, ClientBook, Research) or a grid of
// WidgetContainers across every state, loading skeletons included (the multi-card
// dashboards). All of these already supply bordered, padded cards, so CanvasTile
// must NOT add its own p-4 inset or the cards read as double-framed (TASK-069).
// Every OTHER widget renders bare content (a plain title + inner blocks) and relies
// on CanvasTile's padding so it doesn't sit flush against the tile edge.
export const SELF_CONTAINED = new Set<string>([
  // Single-card.
  "ChangeRadar",
  "ClientBook",
  "Research",
  // Multi-card dashboards — own a full card grid in ok/loading/error states.
  "BeforeAfter",
  "Client360",
  "EmailDraft",
  "MeetingPrep",
  "PortfolioView",
]);
