import { useState, useEffect } from "react";
import { getPortfolioFit } from "../../api/portfolio";
import type { HoldingFit, PortfolioFitResponse } from "../../api/portfolio";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: PortfolioFitResponse }
  | { kind: "error"; message: string };

const SVG_W = 400;
const SVG_H = 280;

interface SectorData {
  name: string;
  chf: number;
  avgFit: number | null;
}

function sectorFillColor(avgFit: number | null): string {
  if (avgFit === null) return "var(--color-panel3)";
  if (avgFit === 0) return "var(--color-red)";
  if (avgFit >= 0.75) return "var(--color-green)";
  return "var(--color-amber)";
}

function computeSectors(holdings: HoldingFit[]): SectorData[] {
  const map = new Map<string, { chf: number; scores: number[] }>();
  for (const h of holdings) {
    const key = h.industry_group ?? "Other";
    const existing = map.get(key) ?? { chf: 0, scores: [] };
    existing.chf += h.current_chf ?? 0;
    if (h.fit_score !== null) existing.scores.push(h.fit_score);
    map.set(key, existing);
  }
  return Array.from(map.entries())
    .map(([name, { chf, scores }]) => ({
      name,
      chf,
      avgFit: scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null,
    }))
    .sort((a, b) => b.chf - a.chf);
}

interface CellProps {
  x: number;
  y: number;
  w: number;
  h: number;
  sector: SectorData;
}

function TreemapCell({ x, y, w, h, sector }: CellProps) {
  const fill = sectorFillColor(sector.avgFit);
  const chfK =
    sector.chf >= 1_000_000
      ? `${(sector.chf / 1_000_000).toFixed(1)}M`
      : `${(sector.chf / 1_000).toFixed(0)}K`;
  const showLabel = w > 50 && h > 22;
  const showChf = w > 60 && h > 36;

  return (
    <g>
      <rect
        x={x + 1}
        y={y + 1}
        width={Math.max(w - 2, 0)}
        height={Math.max(h - 2, 0)}
        fill={fill}
        fillOpacity="0.25"
        rx="4"
        stroke={fill}
        strokeOpacity="0.5"
        strokeWidth="1"
      />
      {showLabel && (
        <text
          x={x + w / 2}
          y={y + (showChf ? h / 2 - 6 : h / 2 + 4)}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize="10"
          fill="var(--color-text)"
          fontWeight="500"
        >
          {sector.name.length > 14 ? sector.name.slice(0, 13) + "…" : sector.name}
        </text>
      )}
      {showChf && (
        <text
          x={x + w / 2}
          y={y + h / 2 + 8}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize="9"
          fill="var(--color-muted)"
        >
          {chfK}
        </text>
      )}
    </g>
  );
}

interface SectorTreemapProps {
  clientId: string;
}

export function SectorTreemap({ clientId }: SectorTreemapProps) {
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
        <div className="h-[280px] w-full animate-pulse rounded bg-panel3" />
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <div className="rounded-2xl border border-border bg-panel p-4 text-[13px]">
        <p className="text-muted">Could not load sector treemap.</p>
        <p className="mt-1 text-dim text-[11px]">{status.message}</p>
      </div>
    );
  }

  const { data } = status;
  const sectors = computeSectors(data.holdings);
  const totalChf = sectors.reduce((s, r) => s + r.chf, 0);

  // Row-sliced layout: each sector gets a proportional horizontal strip
  let y = 0;
  const cells = sectors.map((sector) => {
    const h = totalChf > 0 ? (sector.chf / totalChf) * SVG_H : 0;
    const cell = { x: 0, y, w: SVG_W, h, sector };
    y += h;
    return cell;
  });

  return (
    <div className="rounded-2xl border border-border bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-semibold text-[15px] text-text">Sector Treemap</span>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-red">● conflict</span>
          <span className="text-amber">● partial</span>
          <span className="text-green">● clean</span>
        </div>
      </div>

      {sectors.length === 0 ? (
        <p className="text-[13px] text-muted">
          No holdings to show for this client yet.
        </p>
      ) : (
        <svg
          width="100%"
          viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          aria-label="Sector allocation treemap"
        >
          {cells.map(({ x, y: cy, w, h, sector }) => (
            <TreemapCell
              key={sector.name}
              x={x}
              y={cy}
              w={w}
              h={h}
              sector={sector}
            />
          ))}
        </svg>
      )}

      <p className="mt-2 pt-3 border-t border-border text-[11px] text-dim">
        Source: Portfolio positions · CIO tags
      </p>
    </div>
  );
}
