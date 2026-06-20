import { useState, useEffect } from "react";
import { getPortfolioAllocation } from "../../api/portfolio";
import type { AllocationResponse, SACRow } from "../../api/portfolio";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: AllocationResponse }
  | { kind: "error"; message: string };

const PALETTE = [
  "var(--color-blue)",
  "var(--color-teal)",
  "var(--color-amber)",
  "var(--color-purple)",
  "var(--color-green)",
  "var(--color-red)",
  "#64748b", // slate
  "#0ea5e9", // sky
  "#d946ef", // fuchsia
  "#f97316", // orange
];

const CX = 130;
const CY = 130;
const R_OUTER = 100;
const R_INNER = 62;

function arcPath(startAngle: number, endAngle: number): string {
  const x1 = CX + R_OUTER * Math.cos(startAngle);
  const y1 = CY + R_OUTER * Math.sin(startAngle);
  const x2 = CX + R_OUTER * Math.cos(endAngle);
  const y2 = CY + R_OUTER * Math.sin(endAngle);
  const xi1 = CX + R_INNER * Math.cos(endAngle);
  const yi1 = CY + R_INNER * Math.sin(endAngle);
  const xi2 = CX + R_INNER * Math.cos(startAngle);
  const yi2 = CY + R_INNER * Math.sin(startAngle);
  const large = endAngle - startAngle > Math.PI ? 1 : 0;
  return [
    `M ${x1} ${y1}`,
    `A ${R_OUTER} ${R_OUTER} 0 ${large} 1 ${x2} ${y2}`,
    `L ${xi1} ${yi1}`,
    `A ${R_INNER} ${R_INNER} 0 ${large} 0 ${xi2} ${yi2}`,
    "Z",
  ].join(" ");
}

function chfCompact(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return String(Math.round(v));
}

interface AllocationDonutProps {
  clientId: string;
}

export function AllocationDonut({ clientId }: AllocationDonutProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [hoveredSac, setHoveredSac] = useState<string | null>(null);

  useEffect(() => {
    setStatus({ kind: "loading" });
    const ctrl = new AbortController();
    getPortfolioAllocation(clientId, ctrl.signal)
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
      <div className="rounded-[14px] border border-border bg-panel p-4 space-y-3">
        <div className="h-5 w-32 animate-pulse rounded bg-panel3" />
        <div className="h-[260px] w-[260px] mx-auto animate-pulse rounded-full bg-panel3" />
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px]">
        <p className="text-muted">Could not load allocation.</p>
        <p className="mt-1 text-dim text-[11px]">{status.message}</p>
      </div>
    );
  }

  const { data } = status;
  // Sort by current_chf desc for consistent arc ordering
  const rows: SACRow[] = [...data.sac_rows].sort((a, b) => b.current_chf - a.current_chf);

  // Build arcs
  let angle = -Math.PI / 2; // start at top
  const arcs = rows.map((row, i) => {
    const span = (row.current_pct / 100) * 2 * Math.PI;
    const start = angle;
    const end = angle + span;
    angle = end;
    return { row, start, end, color: PALETTE[i % PALETTE.length] };
  });

  return (
    <div className="rounded-[14px] border border-border bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-semibold text-[15px] text-text">Allocation</span>
        <span className="text-[12px] text-muted">{data.mandate}</span>
      </div>

      {rows.length === 0 ? (
        <p className="text-[13px] text-muted">
          No positions seeded. Run{" "}
          <code className="font-mono text-dim">POST /admin/seed/portfolio</code> first.
        </p>
      ) : (
        <div className="flex flex-col items-center">
          <svg width="260" height="260" viewBox="0 0 260 260" aria-label="Allocation donut">
            {arcs.map(({ row, start, end, color }) => (
              <path
                key={row.sub_asset_class}
                d={arcPath(start, end)}
                fill={color}
                fillOpacity={hoveredSac === null || hoveredSac === row.sub_asset_class ? 1 : 0.35}
                onMouseEnter={() => setHoveredSac(row.sub_asset_class)}
                onMouseLeave={() => setHoveredSac(null)}
                className="cursor-pointer transition-opacity"
              />
            ))}
            {/* Center label */}
            <text
              x={CX}
              y={CY - 6}
              textAnchor="middle"
              fontSize="11"
              fill="var(--color-muted)"
            >
              Total CHF
            </text>
            <text
              x={CX}
              y={CY + 10}
              textAnchor="middle"
              fontSize="15"
              fontWeight="600"
              fill="var(--color-text)"
            >
              {chfCompact(data.total_chf)}
            </text>
          </svg>

          {/* Legend */}
          <div className="w-full mt-1 space-y-1">
            {arcs.map(({ row, color }) => (
              <div
                key={row.sub_asset_class}
                className="flex items-center gap-2 text-[11px]"
                onMouseEnter={() => setHoveredSac(row.sub_asset_class)}
                onMouseLeave={() => setHoveredSac(null)}
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span className="flex-1 truncate text-muted">{row.sub_asset_class}</span>
                <span className="font-mono text-dim">{row.current_pct.toFixed(1)}%</span>
                {row.breach && (
                  <span className="text-red font-bold">!</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="mt-3 pt-3 border-t border-border text-[11px] text-dim">
        Source: CIO Mandate Strategy
      </p>
    </div>
  );
}
