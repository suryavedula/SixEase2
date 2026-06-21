// Shared formatting + status-colour helpers for the generative-UI widgets.
// These were previously redefined per-widget (chfCompact in 3 files, chfFormat in
// 2, fit colour/percent inline in several); consolidating them keeps CHF rounding
// and the fit-score colour bands identical everywhere.

// Compact CHF for tight labels (chart centres, radar rows): 1.23M / 45K / 320.
// `—` for null/zero so empty cells read cleanly.
export function chfCompact(v: number | null | undefined): string {
  if (!v) return "—";
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return String(Math.round(v));
}

// Full CHF with Swiss thousands separators: "CHF 1'234'567".
export function chfFormat(v: number | null | undefined): string {
  if (v == null) return "—";
  return `CHF ${v.toLocaleString("de-CH", { maximumFractionDigits: 0 })}`;
}

// Fit-score → Tailwind text colour. Bands match the data-status palette:
// 0 = conflict (red), ≥0.75 = aligned (green), in-between = partial (amber).
export function fitColor(score: number | null | undefined): string {
  if (score == null) return "text-dim";
  if (score === 0) return "text-red";
  if (score >= 0.75) return "text-green";
  return "text-amber";
}

// Fit score (0–1) → integer percent label, e.g. "75%". `—` when unknown.
export function fitPct(score: number | null | undefined): string {
  return score != null ? `${Math.round(score * 100)}%` : "—";
}

// Accessible status badges: pair the colour with an icon + label so meaning
// never depends on colour alone (colorblind safety). Returns a lucide icon
// component, a text label, a Tailwind colour class, and an aria description.
import { Check, Minus, X, AlertTriangle, type LucideIcon } from "lucide-react";

export interface StatusBadge {
  Icon: LucideIcon;
  label: string;
  className: string;
  aria: string;
}

// Fit score → aligned (✓) / partial (–) / conflict (✗), matching fitColor bands.
export function fitStatusBadge(score: number | null | undefined): StatusBadge {
  if (score == null)
    return { Icon: Minus, label: "—", className: "text-dim", aria: "fit unknown" };
  if (score === 0)
    return { Icon: X, label: fitPct(score), className: "text-red", aria: "values conflict" };
  if (score >= 0.75)
    return { Icon: Check, label: fitPct(score), className: "text-green", aria: "values aligned" };
  return { Icon: Minus, label: fitPct(score), className: "text-amber", aria: "partial fit" };
}

// Drift breach → ⚠ Breach (red) / ✓ In band (green).
export function breachBadge(breach: boolean): StatusBadge {
  return breach
    ? { Icon: AlertTriangle, label: "Breach", className: "text-red", aria: "drift breach" }
    : { Icon: Check, label: "In band", className: "text-green", aria: "within band" };
}
