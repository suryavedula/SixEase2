import { useState, useEffect } from "react";
import { getPortfolioSwaps } from "../../api/portfolio";
import type { SwapProposalsResponse, PositionSwaps, KeptPosition } from "../../api/portfolio";
import { SourcesFooter } from "./SourcesFooter";
import type { DisplaySource } from "./SourcesFooter";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: SwapProposalsResponse }
  | { kind: "error"; message: string };

function fitColor(score: number | null): string {
  if (score === null) return "text-dim";
  if (score === 0) return "text-red";
  if (score >= 0.75) return "text-green";
  return "text-amber";
}

function chfFormat(v: number | null): string {
  if (v === null) return "—";
  return `CHF ${v.toLocaleString("de-CH", { maximumFractionDigits: 0 })}`;
}

function ScoreDot({ score }: { score: number | null }) {
  return (
    <span className={`text-[11px] font-mono ${fitColor(score)}`}>
      ● {score !== null ? `${Math.round(score * 100)}%` : "—"}
    </span>
  );
}

function SwapCard({ pos }: { pos: PositionSwaps }) {
  const best = pos.candidates[0];
  if (!best) return null;

  const projectedScore =
    pos.current_fit_score !== null && best.fit_gain !== null
      ? pos.current_fit_score + best.fit_gain
      : null;

  const conflictTags = (pos.conflict_tags ?? []) as string[];

  const swapSources: DisplaySource[] = [];
  if (best.dna_reason) {
    swapSources.push({ id: "dna", kind: "CRM", label: "DNA Rationale", detail: best.dna_reason, url: null, date: null });
  }
  if (best.candidate_cio_view) {
    swapSources.push({ id: "cio", kind: "CIO", label: "CIO Recommendation", detail: `BUY · ${best.candidate_cio_view}`, url: null, date: null });
  }

  return (
    <div className="rounded-lg border border-border bg-panel2 p-3">
      {/* Before → After panels */}
      <div className="flex items-stretch gap-2">
        {/* BEFORE */}
        <div className="flex-1 rounded-md border border-red/20 bg-red/5 p-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-dim mb-1.5">
            Before
          </p>
          <p className="text-[13px] font-semibold text-text leading-snug">
            {pos.issuer ?? "—"}
          </p>
          <p className="text-[11px] text-muted leading-snug mb-1.5">{pos.security ?? "—"}</p>
          <ScoreDot score={pos.current_fit_score} />
          <p className="mt-1 text-[11px] text-muted">{chfFormat(pos.current_chf)}</p>
          {conflictTags.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {conflictTags.map((tag) => (
                <span
                  key={tag}
                  className="rounded border border-red/30 bg-red/10 px-1.5 py-0.5 text-[10px] text-red"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Arrow */}
        <div className="flex items-center shrink-0 text-dim text-lg">→</div>

        {/* AFTER */}
        <div className="flex-1 rounded-md border border-green/20 bg-green/5 p-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-dim mb-1.5">
            After
          </p>
          <p className="text-[13px] font-semibold text-text leading-snug">
            {best.candidate_issuer ?? best.candidate_isin ?? "—"}
          </p>
          <p className="text-[11px] text-muted leading-snug mb-1.5">
            {best.candidate_security ?? "—"}
          </p>
          <ScoreDot score={projectedScore} />
          {best.fit_gain !== null && (
            <p className="mt-1 text-[11px] font-mono text-green">
              +{Math.round(best.fit_gain * 100)}pp fit
            </p>
          )}
        </div>
      </div>

      {/* Proof strip */}
      <div className="mt-2.5 rounded-md border border-border bg-panel3 px-2.5 py-2 space-y-1.5">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="rounded border border-blue/20 bg-blue/10 px-1.5 py-0.5 text-[10px] font-semibold text-blue">
            Mandate neutral
          </span>
          <span className="text-[11px] text-muted">Same sub-asset class — portfolio weight unchanged</span>
        </div>
        {best.dna_reason && (
          <div className="flex items-start gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-dim shrink-0 mt-0.5">
              DNA
            </span>
            <span className="text-[11px] text-muted">{best.dna_reason}</span>
          </div>
        )}
        {best.candidate_cio_view && (
          <div className="flex items-start gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-dim shrink-0 mt-0.5">
              CIO
            </span>
            <span className="text-[11px] text-muted">BUY · {best.candidate_cio_view}</span>
          </div>
        )}
      </div>

      <SourcesFooter sources={swapSources} />
    </div>
  );
}

function KeptCard({ pos }: { pos: KeptPosition }) {
  const conflictTags = (pos.conflict_tags ?? []) as string[];
  return (
    <div className="rounded-lg border border-border bg-panel2 p-3">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="rounded border border-amber/20 bg-amber/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber">
          No swap available
        </span>
        <span className="text-[13px] font-semibold text-text">{pos.issuer ?? "—"}</span>
      </div>
      <p className="text-[11px] text-muted mb-1">{pos.security ?? "—"}</p>
      {conflictTags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {conflictTags.map((tag) => (
            <span
              key={tag}
              className="rounded border border-red/30 bg-red/10 px-1.5 py-0.5 text-[10px] text-red"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
      {pos.keep_reason && (
        <p className="text-[11px] text-dim">{pos.keep_reason}</p>
      )}
    </div>
  );
}

interface SwapBeforeAfterProps {
  clientId: string;
  positionId?: string;
}

export function SwapBeforeAfter({ clientId, positionId }: SwapBeforeAfterProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    setStatus({ kind: "loading" });
    const ctrl = new AbortController();
    getPortfolioSwaps(clientId, ctrl.signal)
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
        <div className="h-5 w-44 animate-pulse rounded bg-panel3" />
        <div className="h-20 w-full animate-pulse rounded bg-panel3" />
        <div className="h-20 w-full animate-pulse rounded bg-panel3" />
      </div>
    );
  }

  if (status.kind === "error") {
    const is404 = status.message.includes("404");
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px]">
        {is404 ? (
          <p className="text-muted">
            No portfolio data — run{" "}
            <code className="font-mono text-dim">POST /admin/seed/portfolio</code> first.
          </p>
        ) : (
          <>
            <p className="text-muted">Could not load swap proposals.</p>
            <p className="mt-1 text-dim text-[11px]">{status.message}</p>
          </>
        )}
      </div>
    );
  }

  const { data } = status;

  const swapPositions = positionId
    ? data.positions.filter((p) => p.position_id === positionId)
    : data.positions;

  const keptPositions = positionId
    ? data.kept_positions.filter((p) => p.position_id === positionId)
    : data.kept_positions;

  const hasAnything = swapPositions.length > 0 || keptPositions.length > 0;

  return (
    <div className="rounded-[14px] border border-border bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-semibold text-[15px] text-text">Swap Proposals</span>
        <span className="text-[12px] text-muted">
          {data.total_proposals} proposal{data.total_proposals !== 1 ? "s" : ""} ·{" "}
          {data.conflict_positions} conflict{data.conflict_positions !== 1 ? "s" : ""}
        </span>
      </div>

      {!hasAnything ? (
        <p className="text-[13px] text-muted">
          {data.conflict_positions === 0
            ? "No conflicts detected — all holdings are DNA-compliant."
            : "No swap seed run yet. Run POST /admin/seed/swap to compute proposals."}
        </p>
      ) : (
        <div className="space-y-3 overflow-y-auto max-h-[640px] pr-0.5">
          {swapPositions.map((pos) => (
            <SwapCard key={pos.position_id} pos={pos} />
          ))}
          {keptPositions.map((pos) => (
            <KeptCard key={pos.position_id} pos={pos} />
          ))}
        </div>
      )}
    </div>
  );
}
