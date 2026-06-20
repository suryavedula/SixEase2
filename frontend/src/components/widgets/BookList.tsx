import { useState, useEffect } from "react";
import { getBook } from "../../api/book";
import type { BookClient, BookResponse, BookSwapSummary } from "../../api/book";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: BookResponse }
  | { kind: "error"; message: string };

function mandateBadgeClass(mandate: string): string {
  const m = mandate.toUpperCase();
  if (m === "BALANCED") return "bg-blue/10 text-blue border-blue/20";
  if (m === "GROWTH") return "bg-green/10 text-green border-green/20";
  if (m === "DEFENSIVE") return "bg-purple/10 text-purple border-purple/20";
  return "bg-panel3 text-muted border-border";
}

function FitBar({ value }: { value: number | null }) {
  if (value === null) {
    return <span className="text-[12px] text-dim">—</span>;
  }
  const pct = Math.round(value * 100);
  return (
    <div className="mt-1.5 flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-panel3">
        <div
          className="h-1.5 rounded-full bg-green transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[11px] font-mono text-muted w-8 text-right">{pct}%</span>
    </div>
  );
}

function SwapRow({ swap }: { swap: BookSwapSummary }) {
  const gain = swap.fit_gain !== null ? `+${Math.round(swap.fit_gain * 100)}pp` : null;
  return (
    <li className="text-[12px] text-muted leading-snug">
      <span className="text-text">{swap.from_security ?? "—"}</span>
      <span className="text-dim mx-1">→</span>
      <span className="text-text">{swap.to_security ?? "—"}</span>
      {gain && <span className="ml-2 font-mono text-green">{gain}</span>}
      {swap.dna_reason && (
        <span className="ml-1 text-dim">· {swap.dna_reason}</span>
      )}
    </li>
  );
}

function ClientRow({ client }: { client: BookClient }) {
  const [expanded, setExpanded] = useState(false);
  const hasConflicts = client.conflict_positions > 0;
  const hasProposals = client.proposal_count > 0;
  const keptOnly = client.kept_count > 0 && !hasProposals;

  return (
    <div className="rounded-lg border border-border bg-panel2">
      <button
        type="button"
        className="w-full text-left px-3 pt-3 pb-2"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="flex items-center gap-2">
          <span className="font-semibold text-[13px] text-text flex-1 truncate">
            {client.client_name}
          </span>
          <span
            className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${mandateBadgeClass(client.mandate)}`}
          >
            {client.mandate}
          </span>
          <span className="shrink-0 text-dim text-[11px]">{expanded ? "▲" : "▼"}</span>
        </div>
        <FitBar value={client.portfolio_fit} />
        <div className="mt-1 flex gap-2 flex-wrap">
          {hasConflicts && (
            <span className="text-[11px] text-red">
              {client.conflict_positions} conflict{client.conflict_positions !== 1 ? "s" : ""}
            </span>
          )}
          {hasProposals && (
            <span className="text-[11px] text-green">
              {client.proposal_count} swap{client.proposal_count !== 1 ? "s" : ""}
            </span>
          )}
          {keptOnly && (
            <span className="text-[11px] text-amber">
              {client.kept_count} kept
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 border-t border-border mt-1 pt-2">
          {client.top_swaps.length > 0 ? (
            <ul className="space-y-1.5">
              {client.top_swaps.map((swap, i) => (
                <SwapRow key={i} swap={swap} />
              ))}
            </ul>
          ) : keptOnly ? (
            <p className="text-[12px] text-dim">
              Conflict reviewed — no compliant swap available.
            </p>
          ) : hasConflicts ? (
            <p className="text-[12px] text-dim">
              Swap seed not yet run.
            </p>
          ) : (
            <p className="text-[12px] text-dim">No conflicts detected.</p>
          )}
        </div>
      )}
    </div>
  );
}

interface BookListProps {
  mandate?: string;
}

export function BookList({ mandate }: BookListProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    setStatus({ kind: "loading" });
    const ctrl = new AbortController();
    getBook(mandate, ctrl.signal)
      .then((data) => setStatus({ kind: "ok", data }))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setStatus({ kind: "error", message });
      });
    return () => ctrl.abort();
  }, [mandate]);

  if (status.kind === "loading") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 space-y-3">
        <div className="h-5 w-40 animate-pulse rounded bg-panel3" />
        <div className="h-3 w-full animate-pulse rounded bg-panel3" />
        <div className="h-3 w-3/4 animate-pulse rounded bg-panel3" />
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px]">
        <p className="text-muted">Could not load book view.</p>
        <p className="mt-1 text-dim text-[11px]">{status.message}</p>
      </div>
    );
  }

  const { data } = status;

  return (
    <div className="rounded-[14px] border border-border bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-semibold text-[15px] text-text">Book View</span>
        <span className="text-[12px] text-muted">
          {data.scored_clients}/{data.total_clients} scored
        </span>
      </div>
      {data.clients.length === 0 ? (
        <p className="text-[13px] text-muted">
          No clients found. Run{" "}
          <code className="font-mono text-dim">POST /admin/seed/portfolio</code> to populate.
        </p>
      ) : (
        <div className="space-y-1.5 overflow-y-auto max-h-[600px] pr-0.5">
          {data.clients.map((client) => (
            <ClientRow key={client.client_id} client={client} />
          ))}
        </div>
      )}

      <p className="mt-3 pt-3 border-t border-border text-[11px] text-dim">
        Source: Portfolio positions
      </p>
    </div>
  );
}
