import type { ComponentType } from "react";
import {
  AllocationDonut,
  BookList,
  ChatMessage,
  ConflictsList,
  DnaCard,
  DnaRadar,
  DriftBars,
  FitHeatmap,
  HoldingsTable,
  MessageDraftPanel,
  MessageDraftWidget,
  RelationshipTimeline,
  SectorTreemap,
  SwapBeforeAfter,
  TaskResultCard,
} from "../components/widgets";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const registry = new Map<string, ComponentType<any>>([
  ["AllocationDonut", AllocationDonut],
  ["BookList", BookList],
  ["ChatMessage", ChatMessage],
  ["ConflictsList", ConflictsList],
  ["DnaCard", DnaCard],
  ["DnaRadar", DnaRadar],
  ["DriftBars", DriftBars],
  ["FitHeatmap", FitHeatmap],
  ["HoldingsTable", HoldingsTable],
  ["MessageDraftPanel", MessageDraftPanel],
  ["MessageDraftWidget", MessageDraftWidget],
  ["RelationshipTimeline", RelationshipTimeline],
  ["SectorTreemap", SectorTreemap],
  ["SwapBeforeAfter", SwapBeforeAfter],
  ["TaskResultCard", TaskResultCard],
]);
