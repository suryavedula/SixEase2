import { useState, useEffect } from "react";
import { fitStatusBadge } from "../../lib/format";
import { getPortfolioFit } from "../../api/portfolio";
import type { HoldingFit, PortfolioFitResponse } from "../../api/portfolio";
import { SourcesFooter } from "./SourcesFooter";
import type { DisplaySource } from "./SourcesFooter";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: PortfolioFitResponse }
  | { kind: "error"; message: string };

function chipColors(score: number | null): { bg: string; border: string; text: string } {
  if (score === null) return { bg: "bg-panel3", border: "border-border", text: "text-dim" };
  if (score === 0) return { bg: "bg-red/20", border: "border-red/30", text: "text-red" };
  if (score >= 0.75) return { bg: "bg-green/20", border: "border-green/30", text: "text-green" };
  return { bg: "bg-amber/20", border: "border-amber/30", text: "text-amber" };
}

function issuerAbbr(issuer: string | null): string {
  if (!issuer) return "??";
  const words = issuer.trim().split(/\s+/);
  if (words.length === 1) return words[0].slice(0, 4).toUpperCase();
  return words
    .slice(0, 3)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

function HoldingChip({ h }: { h: HoldingFit }) {
  const { bg, border, text } = chipColors(h.fit_score);
  const conflictCount = (h.conflicts ?? []).filter((c) => c.impact === "exclusion").length;
  const pct = h.fit_score !== null ? `${Math.round(h.fit_score * 100)}%` : "—";
  const badge = fitStatusBadge(h.fit_score);
  const BadgeIcon = badge.Icon;
  const tooltip = [
    h.issuer ?? "Unknown",
    h.security ?? "",
    `Fit: ${pct}`,
    conflictCount > 0 ? `${conflictCount} conflict(s)` : "",
    h.sub_asset_class ?? "",
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <div
      title={tooltip}
      aria-label={`${h.issuer ?? "Holding"} — ${badge.aria}, fit ${pct}`}
      className={`rounded border px-2 py-1 text-center cursor-default ${bg} ${border}`}
    >
      <div className={`flex items-center justify-center gap-0.5 text-[11px] font-mono font-semibold ${text}`}>
        <BadgeIcon className="h-3 w-3" aria-hidden /> {pct}
      </div>
      <div className="text-[10px] text-dim leading-tight truncate max-w-[56px]">
        {issuerAbbr(h.issuer)}
      </div>
    </div>
  );
}

interface FitHeatmapProps {
  clientId: string;
}

export function FitHeatmap({ clientId }: FitHeatmapProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    setStatus({ kind: "loading" });
    const ctrl = new AbortController();
    getPortfolioFit(clientId, ctrl.signal)
      .then((data) => setStatus({ kind: "ok", data }))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setStatus({ kind: "error", message });
      });
    return () => ctrl.abort();
  }, [clientId]);

  if (status.kind === "loading") {
    return (
      <div className="rounded-2xl border border-border bg-panel p-4 space-y-3">
        <div className="h-5 w-32 animate-pulse rounded bg-panel3" />
        <div className="flex flex-wrap gap-1.5">
          {Array.from({ length: 12 }, (_, i) => (
            <div key={i} className="h-12 w-14 animate-pulse rounded bg-panel3" />
          ))}
        </div>
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <div className="rounded-2xl border border-border bg-panel p-4 text-[13px]">
        <p className="text-muted">Could not load fit heatmap.</p>
        <p className="mt-1 text-dim text-[11px]">{status.message}</p>
      </div>
    );
  }

  const { data } = status;
  // Sort by fit_score asc (conflicts first)
  const sorted = [...data.holdings].sort((a, b) => (a.fit_score ?? 0.5) - (b.fit_score ?? 0.5));

  const cioSources: DisplaySource[] = data.holdings
    .filter((h) => h.cio_view)
    .map((h) => ({
      id: h.position_id,
      kind: "CIO" as const,
      label: h.issuer ?? h.industry_group ?? "Holding",
      detail: h.cio_view!,
      url: null,
      date: null,
    }));

  return (
    <div className="rounded-2xl border border-border bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-semibold text-[15px] text-text">Fit Heatmap</span>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-red">● conflict</span>
          <span className="text-amber">● partial</span>
          <span className="text-green">● clean</span>
        </div>
      </div>

      {sorted.length === 0 ? (
        <p className="text-[13px] text-muted">
          No holdings to show for this client yet.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {sorted.map((h) => (
            <HoldingChip key={h.position_id} h={h} />
          ))}
        </div>
      )}

      <SourcesFooter sources={cioSources} />
    </div>
  );
}
