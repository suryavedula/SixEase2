import { useEffect, useState } from "react";
import { chfFormat, fitColor, fitPct } from "../../lib/format";
import { ArrowRight, Check, ShieldCheck, X } from "lucide-react";
import {
  decideSwaps,
  getPortfolioAllocation,
  getPortfolioFit,
  getPortfolioSwaps,
  type AllocationResponse,
  type ConflictItem,
  type HoldingFit,
  type KeptPosition,
  type PortfolioFitResponse,
  type PositionSwaps,
  type SwapProposalsResponse,
} from "../../api/portfolio";
import { WidgetContainer } from "./WidgetContainer";
import { SourcesFooter, type DisplaySource } from "./SourcesFooter";
import { useToast } from "../../context/ToastProvider";
import { useCanvasActions } from "../shell/CanvasActions";

// TASK-065 — the "values honoured · within CIO" pitch screen. Consolidates the
// deleted SwapBeforeAfter into one widget that serves both modes off the SAME
// endpoints (TASK-064 added no model-baseline variant — a simulated client is a
// first-class client):
//   before = /portfolio/fit holdings   (existing: drifted current · simulated: model)
//   after  = /portfolio/swaps          (best-fit CIO-BUY per conflict slot)
// `mode` drives copy only; the data fetch is identical. Numbers are computed from
// the payload, never authored (grounding); approve only flags for the RM (HITL).

type Mode = "existing" | "simulated";

type Status =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ok";
      fit: PortfolioFitResponse;
      swaps: SwapProposalsResponse | null;
      alloc: AllocationResponse | null;
    };

interface BeforeAfterProps {
  clientId: string;
  mode?: Mode;
}

const COPY: Record<Mode, { before: string; after: string; lead: string }> = {
  existing: {
    before: "Current",
    after: "Swapped",
    lead: "Personalised to this client's values — without leaving the CIO strategy.",
  },
  simulated: {
    before: "Model",
    after: "Personalised",
    lead: "Same house model, same risk — re-filled around this client's values.",
  },
};


// Projected portfolio fit after the surfaced swaps are applied. Replicates the
// backend's exposure-weighted mean (routers/portfolio.py:105-109) over the same
// holdings, substituting each swapped slot's fit with current_fit + fit_gain.
function projectedFit(
  holdings: HoldingFit[],
  gainByPosition: Map<string, number>,
): number | null {
  let num = 0;
  let den = 0;
  for (const h of holdings) {
    if (h.current_chf == null || h.fit_score == null) continue;
    const gain = gainByPosition.get(h.position_id);
    const score = gain != null ? h.fit_score + gain : h.fit_score;
    num += h.current_chf * score;
    den += h.current_chf;
  }
  return den > 0 ? num / den : null;
}

export function BeforeAfter({ clientId, mode }: BeforeAfterProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);
  const { toast } = useToast();
  const { refreshTasks } = useCanvasActions();

  // Persist the RM's decision (HITL): records a Task, never trades. Optimistic;
  // reverts on failure so the buttons reappear for a retry.
  async function decide(choice: "approved" | "rejected") {
    setDecision(choice);
    try {
      await decideSwaps(clientId, choice);
      refreshTasks();
      toast({
        message:
          choice === "approved"
            ? "Swap approved — added to your tasks"
            : "Swap rejected — logged to your tasks",
      });
    } catch {
      setDecision(null);
      toast({ message: "Couldn't save your decision — try again" });
    }
  }

  useEffect(() => {
    setStatus({ kind: "loading" });
    setDecision(null);
    const ctrl = new AbortController();
    // Fit is required; swaps + allocation enrich and degrade to null on failure.
    getPortfolioFit(clientId, ctrl.signal)
      .then(async (fit) => {
        const [swaps, alloc] = await Promise.all([
          getPortfolioSwaps(clientId, ctrl.signal).catch(() => null),
          getPortfolioAllocation(clientId, ctrl.signal).catch(() => null),
        ]);
        if (!ctrl.signal.aborted) setStatus({ kind: "ok", fit, swaps, alloc });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setStatus({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, [clientId]);

  if (status.kind === "loading") {
    return (
      <div className="space-y-4">
        <div className="h-24 animate-pulse rounded-2xl bg-panel2" />
        <div className="flex flex-col gap-4 lg:flex-row">
          <div className="h-40 flex-1 animate-pulse rounded-2xl bg-panel2" />
          <div className="h-40 w-full animate-pulse rounded-2xl bg-panel2 lg:w-[260px]" />
        </div>
      </div>
    );
  }

  if (status.kind === "error") {
    const is404 = status.message.includes("404");
    return (
      <WidgetContainer title="Before / After" source="Portfolio Engine">
        {is404 ? (
          <p className="text-[13px] text-muted">
            No portfolio data for this client yet.
          </p>
        ) : (
          <>
            <p className="text-[13px] text-muted">Could not load the before/after view.</p>
            <p className="mt-1 text-[11px] text-dim">{status.message}</p>
          </>
        )}
      </WidgetContainer>
    );
  }

  const { fit, swaps, alloc } = status;
  const resolvedMode: Mode =
    mode ?? (fit.client_name.startsWith("[SIMULATED]") ? "simulated" : "existing");
  const copy = COPY[resolvedMode];

  const positions = swaps?.positions ?? [];
  const kept = swaps?.kept_positions ?? [];
  const resolvedCount = positions.length;

  const gainByPosition = new Map<string, number>();
  for (const p of positions) {
    const best = p.candidates[0];
    if (best?.fit_gain != null) gainByPosition.set(p.position_id, best.fit_gain);
  }

  const fitBefore = fit.portfolio_fit;
  const fitAfter = projectedFit(fit.holdings, gainByPosition);

  // Empty: nothing to personalise — already values- and CIO-aligned.
  if (resolvedCount === 0 && kept.length === 0) {
    return (
      <WidgetContainer title={`Before / After — ${fit.client_name}`} source="Portfolio Engine">
        <div className="flex items-center gap-3 py-6 text-sm text-muted">
          <ShieldCheck className="h-5 w-5 shrink-0 text-green" />
          No conflicts — every holding already aligns with this client&apos;s values and the CIO list.
        </div>
      </WidgetContainer>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Headline — leads with values + CIO, not the raw swaps. */}
      <div className="rounded-2xl border border-green/20 bg-green/5 p-5">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-6 w-6 shrink-0 text-green" />
          <div className="min-w-0">
            <h2 className="text-lg font-semibold tracking-tight text-text">
              Values honoured · 100% within CIO strategy
            </h2>
            <p className="mt-1 text-sm text-muted">
              {fit.client_name} • {fit.mandate} • {copy.lead}
            </p>
            <p className="mt-2 text-sm text-text">
              {resolvedCount > 0 ? (
                <>
                  Replaced <strong>{resolvedCount}</strong> holding{resolvedCount === 1 ? "" : "s"} that
                  conflicted with this client&apos;s values — each with a same-slot CIO-BUY that fits better.
                </>
              ) : (
                <>
                  {kept.length} conflict{kept.length === 1 ? "" : "s"} flagged — no compliant CIO
                  replacement available (see below).
                </>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Proof row: mandate-neutral weights (left) + the headline metrics (right). */}
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          <NeutralityProof alloc={alloc} />
        </div>
        <div className="w-full shrink-0 lg:w-[260px]">
          <WidgetContainer title="Personalisation impact" source="Computed from holdings">
            <dl className="space-y-3 text-sm">
              <Metric label="Portfolio fit">
                <span className={fitColor(fitBefore)}>{fitPct(fitBefore)}</span>
                <ArrowRight className="mx-1.5 inline h-3.5 w-3.5 text-dim" />
                <span className={`font-semibold ${fitColor(fitAfter)}`}>{fitPct(fitAfter)}</span>
              </Metric>
              <Metric label="Conflicts resolved">
                <span className="font-semibold text-text">{resolvedCount}</span>
                {kept.length > 0 && <span className="text-dim"> · {kept.length} unresolved</span>}
              </Metric>
              <Metric label="CIO compliance">
                <span className="font-semibold text-green">Every swap = CIO-BUY</span>
              </Metric>
            </dl>
          </WidgetContainer>
        </div>
      </div>

      {/* Per-swap instrument deltas. */}
      {resolvedCount > 0 && (
        <WidgetContainer
          title="Instrument deltas"
          source="AI Optimiser"
          badges={
            <span className="rounded-full bg-amber/20 px-2 text-[10px] font-bold uppercase tracking-wider text-amber">
              Human Approval Req
            </span>
          }
        >
          <div className="space-y-3">
            {positions.map((p) => (
              <SwapCard key={p.position_id} pos={p} labels={copy} />
            ))}
          </div>
        </WidgetContainer>
      )}

      {/* Conflicts with no compliant swap — surfaced, never dropped (no-fallbacks). */}
      {kept.length > 0 && (
        <WidgetContainer title="Conflicts without a compliant swap" source="Portfolio Engine">
          <div className="space-y-3">
            {kept.map((p) => (
              <KeptCard key={p.position_id} pos={p} />
            ))}
          </div>
        </WidgetContainer>
      )}

      {/* Human-in-the-loop — flags for the RM, never trades. */}
      {resolvedCount > 0 &&
        (decision ? (
          <div
            className={`rounded-xl border p-3 text-center text-sm font-medium ${
              decision === "approved"
                ? "border-green/30 bg-green/10 text-green"
                : "border-border bg-panel2 text-muted"
            }`}
          >
            {decision === "approved"
              ? "Approved — queued for RM review"
              : "Rejected — nothing changed"}
          </div>
        ) : (
          <div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => decide("approved")}
                className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue/90"
              >
                <Check className="h-4 w-4" /> Approve for RM review
              </button>
              <button
                type="button"
                onClick={() => decide("rejected")}
                className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-panel2 py-2.5 text-sm font-medium text-text transition-colors hover:bg-panel3"
              >
                <X className="h-4 w-4" /> Reject
              </button>
            </div>
            <p className="pt-2 text-center text-[11px] text-dim">
              Nothing is executed automatically — approval only flags this for the RM.
            </p>
          </div>
        ))}
    </div>
  );
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-border pb-3 last:border-0 last:pb-0">
      <dt className="text-dim">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

// Mandate-neutral proof: per sub-asset-class weights are identical before & after,
// because personalisation only swaps the instrument within a slot — positions are
// never mutated (TASK-064 _assert_weight_neutral guarantees it).
function NeutralityProof({ alloc }: { alloc: AllocationResponse | null }) {
  return (
    <WidgetContainer title="Strategy unchanged" source="CIO Strategy">
      <p className="mb-3 text-[13px] text-muted">
        Sub-asset-class weights are <strong className="text-text">identical before and after</strong> —
        the mandate never moves; only the instrument filling each slot does.
      </p>
      {alloc && alloc.sac_rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-dim">
                <th className="pb-2 font-medium">Sub-asset class</th>
                <th className="pb-2 text-right font-medium">Before</th>
                <th className="pb-2 text-right font-medium">After</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {alloc.sac_rows.map((r) => {
                const w = `${r.current_pct.toFixed(1)}%`;
                return (
                  <tr key={r.sub_asset_class}>
                    <td className="py-2 text-text">{r.sub_asset_class}</td>
                    <td className="py-2 text-right tabular-nums text-muted">{w}</td>
                    <td className="py-2 text-right tabular-nums text-green">{w}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-[12px] text-dim">
          Allocation breakdown unavailable — weight-neutrality holds by construction (swaps preserve
          each slot&apos;s sub-asset-class and industry group).
        </p>
      )}
    </WidgetContainer>
  );
}

function ScoreDot({ score }: { score: number | null }) {
  return (
    <span className={`font-mono text-[11px] ${fitColor(score)}`}>● {fitPct(score)}</span>
  );
}

function SwapCard({ pos, labels }: { pos: PositionSwaps; labels: { before: string; after: string } }) {
  const best = pos.candidates[0];
  if (!best) return null;

  const projected =
    pos.current_fit_score !== null && best.fit_gain !== null
      ? pos.current_fit_score + best.fit_gain
      : null;
  const conflictTags = pos.conflict_tags ?? [];

  const sources: DisplaySource[] = [];
  if (best.dna_reason) {
    sources.push({ id: `dna-${pos.position_id}`, kind: "CRM", label: "DNA rationale", detail: best.dna_reason, url: null, date: null });
  }
  if (best.candidate_cio_view) {
    sources.push({ id: `cio-${pos.position_id}`, kind: "CIO", label: "CIO recommendation", detail: `BUY · ${best.candidate_cio_view}`, url: null, date: null });
  }

  return (
    <div className="rounded-lg border border-border bg-panel2 p-3">
      <div className="flex items-stretch gap-2">
        {/* BEFORE */}
        <div className="flex-1 rounded-md border border-red/20 bg-red/5 p-2.5">
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-dim">{labels.before}</p>
          <p className="text-[13px] font-semibold leading-snug text-text">{pos.issuer ?? "—"}</p>
          <p className="mb-1.5 text-[11px] leading-snug text-muted">{pos.security ?? "—"}</p>
          <ScoreDot score={pos.current_fit_score} />
          <p className="mt-1 text-[11px] text-muted">{chfFormat(pos.current_chf)}</p>
          <ConflictChips conflicts={conflictTags} className="mt-1.5" />
        </div>

        <div className="flex shrink-0 items-center text-dim">
          <ArrowRight className="h-5 w-5" />
        </div>

        {/* AFTER */}
        <div className="flex-1 rounded-md border border-green/20 bg-green/5 p-2.5">
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-dim">{labels.after}</p>
          <p className="text-[13px] font-semibold leading-snug text-text">
            {best.candidate_issuer ?? best.candidate_isin ?? "—"}
          </p>
          <p className="mb-1.5 text-[11px] leading-snug text-muted">{best.candidate_security ?? "—"}</p>
          <ScoreDot score={projected} />
          {best.fit_gain !== null && (
            <p className="mt-1 font-mono text-[11px] text-green">+{Math.round(best.fit_gain * 100)}pp fit</p>
          )}
        </div>
      </div>

      {/* Proof strip */}
      <div className="mt-2.5 space-y-1.5 rounded-md border border-border bg-panel3 px-2.5 py-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {best.mandate_neutral && (
            <span className="rounded border border-blue/20 bg-blue/10 px-1.5 py-0.5 text-[10px] font-semibold text-blue">
              Mandate neutral
            </span>
          )}
          <span className="text-[11px] text-muted">Same sub-asset class — portfolio weight unchanged</span>
        </div>
        {best.dna_reason && (
          <div className="flex items-start gap-1.5">
            <span className="mt-0.5 shrink-0 text-[10px] font-semibold uppercase tracking-wider text-dim">DNA</span>
            <span className="text-[11px] text-muted">{best.dna_reason}</span>
          </div>
        )}
        {best.candidate_cio_view && (
          <div className="flex items-start gap-1.5">
            <span className="mt-0.5 shrink-0 text-[10px] font-semibold uppercase tracking-wider text-dim">CIO</span>
            <span className="text-[11px] text-muted">BUY · {best.candidate_cio_view}</span>
          </div>
        )}
      </div>

      <SourcesFooter sources={sources} />
    </div>
  );
}

function KeptCard({ pos }: { pos: KeptPosition }) {
  return (
    <div className="rounded-lg border border-border bg-panel2 p-3">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="rounded border border-amber/20 bg-amber/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber">
          No swap available
        </span>
        <span className="text-[13px] font-semibold text-text">{pos.issuer ?? "—"}</span>
      </div>
      <p className="mb-1 text-[11px] text-muted">{pos.security ?? "—"}</p>
      <ConflictChips conflicts={pos.conflict_tags ?? []} className="mb-1.5" />
      {pos.keep_reason && <p className="text-[11px] text-dim">{pos.keep_reason}</p>}
    </div>
  );
}

// Conflict tags arrive as {tag, impact, direction} objects (a holding's DNA
// conflicts), not bare strings — render the tag label and surface impact/direction
// on hover. Tolerates a bare-string element too, in case of legacy payloads.
function ConflictChips({
  conflicts,
  className,
}: {
  conflicts: (ConflictItem | string)[];
  className?: string;
}) {
  if (conflicts.length === 0) return null;
  return (
    <div className={`flex flex-wrap gap-1 ${className ?? ""}`}>
      {conflicts.map((c, i) => {
        const label = typeof c === "string" ? c : c.tag;
        const title =
          typeof c === "string"
            ? undefined
            : [c.impact, c.direction ? `${c.direction > 0 ? "+" : ""}${c.direction}` : null]
                .filter(Boolean)
                .join(" ") || undefined;
        return (
          <span
            key={`${label}-${i}`}
            title={title}
            className="rounded border border-red/30 bg-red/10 px-1.5 py-0.5 text-[10px] text-red"
          >
            {label}
          </span>
        );
      })}
    </div>
  );
}
