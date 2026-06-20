import { useState, useEffect } from "react";
import { getPortfolioAllocation } from "../../api/portfolio";
import type { AllocationResponse, SACRow } from "../../api/portfolio";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: AllocationResponse }
  | { kind: "error"; message: string };

const DRIFT_THRESHOLD = 2.0; // ±2pp mandate band

function DriftBar({ row, maxDrift }: { row: SACRow; maxDrift: number }) {
  const scale = maxDrift > 0 ? maxDrift : DRIFT_THRESHOLD;
  const halfWidth = 50; // each side is 50% of the bar track
  const fillPct = Math.min(Math.abs(row.drift_pp) / scale, 1) * halfWidth;
  const isLeft = row.drift_pp < 0;
  const thresholdPct = Math.min(DRIFT_THRESHOLD / scale, 1) * halfWidth;

  return (
    <div className="mb-3 last:mb-0">
      <div className="flex items-center justify-between mb-0.5">
        <span className="text-[12px] text-text font-medium truncate max-w-[55%]">
          {row.sub_asset_class}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[11px] font-mono text-muted">
            {row.current_pct.toFixed(1)}% / {row.target_pct.toFixed(1)}%
          </span>
          <span
            className={`text-[11px] font-mono font-semibold ${
              row.breach ? "text-red" : "text-green"
            }`}
          >
            {row.drift_pp > 0 ? "+" : ""}
            {row.drift_pp.toFixed(1)}pp
          </span>
        </div>
      </div>

      {/* Bar track */}
      <div className="relative h-2 rounded-full bg-panel3">
        {/* ±2pp band highlight */}
        <div
          className="absolute top-0 h-full rounded-full bg-panel2 opacity-80"
          style={{
            left: `${halfWidth - thresholdPct}%`,
            width: `${thresholdPct * 2}%`,
          }}
        />
        {/* Center tick */}
        <div
          className="absolute top-0 h-full w-px bg-border"
          style={{ left: "50%" }}
        />
        {/* Fill */}
        <div
          className={`absolute top-0 h-full rounded-full ${
            row.breach ? "bg-red" : "bg-green"
          }`}
          style={{
            left: isLeft ? `${halfWidth - fillPct}%` : "50%",
            width: `${fillPct}%`,
          }}
        />
      </div>
    </div>
  );
}

interface DriftBarsProps {
  clientId: string;
}

export function DriftBars({ clientId }: DriftBarsProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

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
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-6 w-full animate-pulse rounded bg-panel3" />
        ))}
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px]">
        <p className="text-muted">Could not load allocation data.</p>
        <p className="mt-1 text-dim text-[11px]">{status.message}</p>
      </div>
    );
  }

  const { data } = status;
  const breachCount = data.sac_rows.filter((r) => r.breach).length;
  const maxDrift = Math.max(...data.sac_rows.map((r) => Math.abs(r.drift_pp)), DRIFT_THRESHOLD);

  return (
    <div className="rounded-[14px] border border-border bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-semibold text-[15px] text-text">Drift vs Mandate</span>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-dim">±2pp band</span>
          {breachCount > 0 ? (
            <span className="rounded border border-red/20 bg-red/10 px-2 py-0.5 text-[11px] font-semibold text-red">
              {breachCount} breach{breachCount !== 1 ? "es" : ""}
            </span>
          ) : (
            <span className="rounded border border-green/20 bg-green/10 px-2 py-0.5 text-[11px] font-semibold text-green">
              All in band
            </span>
          )}
        </div>
      </div>

      {data.sac_rows.length === 0 ? (
        <p className="text-[13px] text-muted">
          No allocation data. Run{" "}
          <code className="font-mono text-dim">POST /admin/seed/portfolio</code> first.
        </p>
      ) : (
        <div>
          {data.sac_rows.map((row) => (
            <DriftBar key={row.sub_asset_class} row={row} maxDrift={maxDrift} />
          ))}
        </div>
      )}

      <p className="mt-3 pt-3 border-t border-border text-[11px] text-dim">
        Source: CIO Mandate Strategy
      </p>
    </div>
  );
}
