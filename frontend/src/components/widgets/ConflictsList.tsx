import { useState, useEffect } from "react";
import { getPortfolioFit } from "../../api/portfolio";
import type { HoldingFit, PortfolioFitResponse } from "../../api/portfolio";
import { getClientDna } from "../../api/dna";
import type { DnaSource } from "../../api/dna";
import { SourcesFooter, dnaSourceToDisplaySource } from "./SourcesFooter";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: PortfolioFitResponse }
  | { kind: "error"; message: string };

function chfFormat(v: number | null): string {
  if (v === null) return "—";
  return `CHF ${v.toLocaleString("de-CH", { maximumFractionDigits: 0 })}`;
}

function ConflictRow({ h }: { h: HoldingFit }) {
  const exclusionTags = (h.conflicts ?? [])
    .filter((c) => c.impact === "exclusion")
    .map((c) => c.tag);

  return (
    <div className="flex items-start gap-3 border-l-2 border-red pl-3 py-1.5">
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-semibold text-text truncate">{h.issuer ?? "—"}</p>
        <p className="text-[11px] text-muted">{h.security ?? "—"}</p>
        <div className="mt-1 flex flex-wrap gap-1">
          {exclusionTags.map((tag) => (
            <span
              key={tag}
              className="rounded border border-red/30 bg-red/10 px-1.5 py-0.5 text-[10px] text-red"
            >
              {tag}
            </span>
          ))}
        </div>
      </div>
      <span className="shrink-0 text-[11px] font-mono text-muted mt-0.5">
        {chfFormat(h.current_chf)}
      </span>
    </div>
  );
}

interface ConflictsListProps {
  clientId: string;
}

export function ConflictsList({ clientId }: ConflictsListProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [dnaSources, setDnaSources] = useState<DnaSource[]>([]);

  useEffect(() => {
    setStatus({ kind: "loading" });
    setDnaSources([]);
    const ctrl = new AbortController();
    let mounted = true;
    getPortfolioFit(clientId, ctrl.signal)
      .then((data) => {
        setStatus({ kind: "ok", data });
        const hasConflicts = data.holdings.some((h) => h.fit_score === 0);
        if (hasConflicts) {
          getClientDna(clientId)
            .then((d) => { if (mounted) setDnaSources(d.sources); })
            .catch(() => {});
        }
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setStatus({ kind: "error", message });
      });
    return () => { ctrl.abort(); mounted = false; };
  }, [clientId]);

  if (status.kind === "loading") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 space-y-3">
        <div className="h-5 w-32 animate-pulse rounded bg-panel3" />
        <div className="h-10 w-full animate-pulse rounded bg-panel3" />
        <div className="h-10 w-full animate-pulse rounded bg-panel3" />
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px]">
        <p className="text-muted">Could not load conflicts.</p>
        <p className="mt-1 text-dim text-[11px]">{status.message}</p>
      </div>
    );
  }

  const { data } = status;
  const conflicts = data.holdings.filter((h) => h.fit_score === 0);

  return (
    <div className="rounded-[14px] border border-border bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-semibold text-[15px] text-text">Conflicts</span>
        {conflicts.length > 0 ? (
          <span className="rounded border border-red/20 bg-red/10 px-2 py-0.5 text-[11px] font-semibold text-red">
            {conflicts.length} holding{conflicts.length !== 1 ? "s" : ""}
          </span>
        ) : (
          <span className="rounded border border-green/20 bg-green/10 px-2 py-0.5 text-[11px] font-semibold text-green">
            None
          </span>
        )}
      </div>

      {conflicts.length === 0 ? (
        <p className="text-[13px] text-green">
          All holdings are DNA-compliant — no exclusion conflicts detected.
        </p>
      ) : (
        <div className="space-y-2 overflow-y-auto max-h-[400px] pr-0.5">
          {conflicts.map((h) => (
            <ConflictRow key={h.position_id} h={h} />
          ))}
        </div>
      )}

      {dnaSources.length > 0 && (
        <SourcesFooter sources={dnaSources.map(dnaSourceToDisplaySource)} />
      )}
    </div>
  );
}
