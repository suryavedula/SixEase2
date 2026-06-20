import { useState, useEffect, Fragment } from "react";
import { getPortfolioFit } from "../../api/portfolio";
import type { HoldingFit, PortfolioFitResponse } from "../../api/portfolio";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: PortfolioFitResponse }
  | { kind: "error"; message: string };

type SortKey = "issuer" | "sub_asset_class" | "industry_group" | "current_chf" | "fit_score";
type SortDir = "asc" | "desc";

function fitDot(score: number | null): string {
  if (score === null) return "text-dim";
  if (score === 0) return "text-red";
  if (score >= 0.75) return "text-green";
  return "text-amber";
}

function chfFormat(v: number | null): string {
  if (v === null) return "—";
  return v.toLocaleString("de-CH", { maximumFractionDigits: 0 });
}

function sortHoldings(holdings: HoldingFit[], key: SortKey, dir: SortDir): HoldingFit[] {
  return [...holdings].sort((a, b) => {
    let va: string | number | null;
    let vb: string | number | null;
    if (key === "current_chf" || key === "fit_score") {
      va = a[key] ?? -Infinity;
      vb = b[key] ?? -Infinity;
    } else {
      va = a[key] ?? "";
      vb = b[key] ?? "";
    }
    if (va < vb) return dir === "asc" ? -1 : 1;
    if (va > vb) return dir === "asc" ? 1 : -1;
    return 0;
  });
}

function SortHeader({
  label,
  col,
  current,
  dir,
  onSort,
}: {
  label: string;
  col: SortKey;
  current: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
}) {
  const active = col === current;
  return (
    <th
      className="text-left text-[11px] font-semibold uppercase tracking-wider text-dim pb-2 pr-3 cursor-pointer select-none hover:text-muted transition-colors"
      onClick={() => onSort(col)}
    >
      {label}
      {active && <span className="ml-1">{dir === "asc" ? "↑" : "↓"}</span>}
    </th>
  );
}

interface HoldingsTableProps {
  clientId: string;
}

export function HoldingsTable({ clientId }: HoldingsTableProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [sortKey, setSortKey] = useState<SortKey>("current_chf");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

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

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  if (status.kind === "loading") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 space-y-2">
        <div className="h-5 w-32 animate-pulse rounded bg-panel3" />
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-8 w-full animate-pulse rounded bg-panel3" />
        ))}
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px]">
        <p className="text-muted">Could not load holdings.</p>
        <p className="mt-1 text-dim text-[11px]">{status.message}</p>
      </div>
    );
  }

  const { data } = status;
  const sorted = sortHoldings(data.holdings, sortKey, sortDir);

  return (
    <div className="rounded-[14px] border border-border bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-semibold text-[15px] text-text">Holdings</span>
        <span className="text-[12px] text-muted">
          {data.scored_holdings}/{data.total_holdings} scored
          {data.portfolio_fit !== null && (
            <> · <span className={fitDot(data.portfolio_fit)}>●</span>{" "}
            {Math.round(data.portfolio_fit * 100)}% fit</>
          )}
        </span>
      </div>

      {data.holdings.length === 0 ? (
        <p className="text-[13px] text-muted">
          No holdings found. Run{" "}
          <code className="font-mono text-dim">POST /admin/seed/portfolio</code> first.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-border">
                <SortHeader label="Issuer" col="issuer" current={sortKey} dir={sortDir} onSort={handleSort} />
                <SortHeader label="Sub-Asset Class" col="sub_asset_class" current={sortKey} dir={sortDir} onSort={handleSort} />
                <SortHeader label="Industry Group" col="industry_group" current={sortKey} dir={sortDir} onSort={handleSort} />
                <SortHeader label="CHF" col="current_chf" current={sortKey} dir={sortDir} onSort={handleSort} />
                <SortHeader label="Fit" col="fit_score" current={sortKey} dir={sortDir} onSort={handleSort} />
                <th className="text-left text-[11px] font-semibold uppercase tracking-wider text-dim pb-2">⚠</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((h) => {
                const conflicts = (h.conflicts ?? []).filter((c) => c.impact === "exclusion");
                const isExpanded = expandedRow === h.position_id;
                return (
                  <Fragment key={h.position_id}>
                    <tr className="border-b border-border/50 hover:bg-panel2 transition-colors">
                      <td className="py-1.5 pr-3 text-text font-medium">
                        <div>{h.issuer ?? "—"}</div>
                        <div className="text-[11px] text-dim">{h.security ?? ""}</div>
                      </td>
                      <td className="py-1.5 pr-3 text-muted">{h.sub_asset_class ?? "—"}</td>
                      <td className="py-1.5 pr-3 text-muted">{h.industry_group ?? "—"}</td>
                      <td className="py-1.5 pr-3 text-muted font-mono">
                        {chfFormat(h.current_chf)}
                      </td>
                      <td className="py-1.5 pr-3">
                        <span className={`font-mono ${fitDot(h.fit_score)}`}>
                          ● {h.fit_score !== null ? `${Math.round(h.fit_score * 100)}%` : "—"}
                        </span>
                      </td>
                      <td className="py-1.5">
                        <div className="flex items-center gap-1">
                          {conflicts.length > 0 && (
                            <span className="rounded bg-red/10 border border-red/20 px-1.5 py-0.5 text-[10px] text-red">
                              {conflicts.length}
                            </span>
                          )}
                          {h.cio_view && (
                            <button
                              type="button"
                              onClick={() => setExpandedRow(isExpanded ? null : h.position_id)}
                              className={`rounded border px-1.5 py-0.5 text-[10px] transition-colors ${
                                isExpanded
                                  ? "border-teal/40 bg-teal/20 text-teal"
                                  : "border-teal/20 bg-teal/10 text-teal hover:bg-teal/20"
                              }`}
                            >
                              CIO
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {isExpanded && h.cio_view && (
                      <tr>
                        <td colSpan={6} className="pb-2 pt-0">
                          <div className="rounded-lg border border-teal/20 bg-teal/5 px-3 py-2 text-[12px] text-muted">
                            <span className="text-[10px] font-semibold uppercase text-teal mr-2">
                              CIO View
                            </span>
                            {h.cio_view}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
