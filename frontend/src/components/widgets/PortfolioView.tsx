import { useEffect, useState } from "react";
import { AlertCircle, ArrowRightLeft, Check, X } from "lucide-react";
import {
  getPortfolioFit,
  getPortfolioSwaps,
  type PortfolioFitResponse,
  type SwapProposalsResponse,
  type HoldingFit,
} from "../../api/portfolio";
import { WidgetContainer } from "./WidgetContainer";

// Ported from Kielis_Advisor_workbech PortfolioViewCanvas, re-tokenised + wired
// to live data: holdings from /portfolio/fit, the swap proposal from
// /portfolio/swaps. Approve/Reject is local human-in-the-loop UI (no auto-trade).

type Status =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; fit: PortfolioFitResponse; swaps: SwapProposalsResponse | null };

function cioClass(view: string | null): string {
  const v = (view ?? "").toLowerCase();
  if (v.includes("buy")) return "bg-green/10 text-green";
  if (v.includes("sell")) return "bg-red/10 text-red";
  return "bg-amber/10 text-amber";
}

function pct(n: number | null | undefined): string {
  return n != null ? `${Math.round(n * 100)}` : "—";
}

interface PortfolioViewProps {
  clientId: string;
}

export function PortfolioView({ clientId }: PortfolioViewProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);

  useEffect(() => {
    setStatus({ kind: "loading" });
    setDecision(null);
    const ctrl = new AbortController();
    getPortfolioFit(clientId, ctrl.signal)
      .then(async (fit) => {
        const swaps = await getPortfolioSwaps(clientId, ctrl.signal).catch(() => null);
        if (!ctrl.signal.aborted) setStatus({ kind: "ok", fit, swaps });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setStatus({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, [clientId]);

  if (status.kind === "loading") {
    return (
      <div className="flex flex-col gap-6 lg:flex-row">
        <div className="h-80 flex-1 animate-pulse rounded-2xl bg-panel2" />
        <div className="h-80 w-full animate-pulse rounded-2xl bg-panel2 lg:w-[380px]" />
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <WidgetContainer title="Portfolio Analysis" source="Live Portfolio">
        <p className="text-[13px] text-muted">Could not load portfolio.</p>
        <p className="mt-1 text-[11px] text-dim">{status.message}</p>
      </WidgetContainer>
    );
  }

  const { fit, swaps } = status;
  const total = fit.holdings.reduce((s, h) => s + (h.current_chf ?? 0), 0) || 1;
  const sorted: HoldingFit[] = [...fit.holdings].sort((a, b) => (b.current_chf ?? 0) - (a.current_chf ?? 0));

  // First position carrying a candidate = the swap to surface.
  const swapPos = swaps?.positions?.find((p) => p.candidates.length > 0) ?? null;
  const candidate = swapPos?.candidates[0] ?? null;
  const conflictCount = fit.holdings.filter(
    (h) => h.fit_score === 0 || (h.conflicts?.length ?? 0) > 0,
  ).length;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-text">Portfolio Analysis</h2>
        <p className="text-sm text-muted">
          {fit.client_name} • {fit.mandate}
        </p>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* Holdings */}
        <div className="min-w-0 flex-1">
          <WidgetContainer title="Holdings & Risks" source="Live Portfolio">
            <div className="overflow-x-auto">
              <table className="w-full whitespace-nowrap text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-dim">
                    <th className="pb-3 font-medium">Instrument</th>
                    <th className="pb-3 font-medium">Class</th>
                    <th className="pb-3 font-medium">Weight</th>
                    <th className="pb-3 font-medium">CIO</th>
                    <th className="pb-3 font-medium">Fit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {sorted.map((h) => {
                    const risk = h.fit_score === 0 || (h.conflicts?.length ?? 0) > 0;
                    return (
                      <tr key={h.position_id} className="transition-colors hover:bg-panel2/40">
                        <td className="flex items-center gap-2 py-3">
                          {risk && <AlertCircle className="h-4 w-4 shrink-0 text-red" />}
                          <span className={risk ? "font-medium text-red" : "text-text"}>
                            {h.issuer || h.security || "—"}
                          </span>
                        </td>
                        <td className="py-3 text-muted">{h.sub_asset_class || "—"}</td>
                        <td className="py-3 text-text">{(((h.current_chf ?? 0) / total) * 100).toFixed(1)}%</td>
                        <td className="py-3">
                          <span
                            className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${cioClass(h.cio_view)}`}
                          >
                            {h.cio_view || "—"}
                          </span>
                        </td>
                        <td className="py-3">
                          <span className={(h.fit_score ?? 0) >= 0.8 ? "text-green" : "text-red"}>
                            {pct(h.fit_score)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </WidgetContainer>
        </div>

        {/* Swap proposal */}
        <div className="w-full shrink-0 lg:w-[380px]">
          <WidgetContainer
            title="AI Swap Proposal"
            source="AI Optimiser"
            badges={
              <span className="rounded-full bg-amber/20 px-2 text-[10px] font-bold uppercase tracking-wider text-amber">
                Human Approval Req
              </span>
            }
          >
            {swapPos && candidate ? (
              <div className="space-y-4">
                <p className="text-sm text-muted">
                  <strong className="text-red">Conflict:</strong> {swapPos.issuer || swapPos.security} conflicts
                  with this client&apos;s red lines.
                </p>

                <div className="relative flex items-center justify-between rounded-xl border border-border bg-panel2/50 p-4">
                  <div className="text-center">
                    <div className="mb-1 text-xs text-dim">Sell</div>
                    <div className="font-semibold text-red">{swapPos.issuer || swapPos.security}</div>
                    <div className="mt-1 text-xs text-muted">{swapPos.sub_asset_class}</div>
                  </div>
                  <ArrowRightLeft className="absolute left-1/2 top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 text-dim" />
                  <div className="text-center">
                    <div className="mb-1 text-xs text-dim">Buy</div>
                    <div className="font-semibold text-green">
                      {candidate.candidate_issuer || candidate.candidate_security}
                    </div>
                    <div className="mt-1 text-xs text-muted">{candidate.candidate_cio_view || "CIO Buy"}</div>
                  </div>
                </div>

                <ul className="mt-4 list-disc space-y-2 pl-4 text-xs text-muted">
                  {candidate.mandate_neutral && <li>Risk-neutral: same sub-asset-class, mandate weights unchanged.</li>}
                  {candidate.fit_gain != null && (
                    <li>Improves values-fit by +{Math.round(candidate.fit_gain * 100)} points.</li>
                  )}
                  {candidate.dna_reason && <li>{candidate.dna_reason}</li>}
                </ul>

                {decision ? (
                  <div
                    className={`mt-4 rounded-lg border p-2 text-center text-sm font-medium ${
                      decision === "approved"
                        ? "border-green/30 bg-green/10 text-green"
                        : "border-border bg-panel2 text-muted"
                    }`}
                  >
                    {decision === "approved" ? "Approved — queued for RM review" : "Rejected"}
                  </div>
                ) : (
                  <div className="mt-4 flex gap-3 border-t border-border pt-4">
                    <button
                      type="button"
                      onClick={() => setDecision("approved")}
                      className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue py-2 text-sm font-medium text-white transition-colors hover:bg-blue/90"
                    >
                      <Check className="h-4 w-4" /> Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => setDecision("rejected")}
                      className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-panel2 py-2 text-sm font-medium text-text transition-colors hover:bg-panel3"
                    >
                      <X className="h-4 w-4" /> Reject
                    </button>
                  </div>
                )}
                <p className="pt-1 text-center text-[11px] text-dim">
                  Nothing is executed automatically — approval only flags this for the RM.
                </p>
              </div>
            ) : conflictCount > 0 ? (
              <div className="py-6 text-center text-sm text-muted">
                {conflictCount} holding{conflictCount === 1 ? "" : "s"} conflict with this client&apos;s
                values, but no qualifying CIO replacement was found. Review manually.
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-muted">
                No conflicts — holdings align with this client&apos;s values and the CIO list.
              </div>
            )}
          </WidgetContainer>
        </div>
      </div>
    </div>
  );
}
