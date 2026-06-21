import { useEffect, useState } from "react";
import { TrendingUp, ArrowRight } from "lucide-react";
import { getBook, type BookClient } from "../../api/book";
import { useCanvasActions } from "../shell/CanvasActions";
import { WidgetContainer } from "./WidgetContainer";

// Ported from Kielis_Advisor_workbech ClientDashboardWidget, re-tokenised + wired
// to /book. Filterable by the orchestrator: it reads the RM's request and sets
// the props below; the widget applies them to the live book. Seed scaffolding
// (Sample mandate clients, [SYNTHETIC] rows) is excluded so this is the real book.

type SortBy = "fit_desc" | "fit_asc" | "conflicts_desc" | "name";

interface ClientBookProps {
  mandate?: string | null; // Defensive | Balanced | Growth
  hasConflicts?: boolean; // only clients with values conflicts
  minFit?: number | null; // 0–100 values-fit floor
  maxFit?: number | null; // 0–100 values-fit ceiling
  sortBy?: SortBy;
  title?: string; // header label describing the filter
  // Widget a row's open button summons for that client (default Client360). Lets
  // the book double as a picker — e.g. open straight into PortfolioView.
  openComponent?: string;
}

type Status =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; clients: BookClient[] };

function isRealClient(c: BookClient): boolean {
  const n = c.client_name;
  return !n.startsWith("Sample ") && !n.startsWith("[SYNTHETIC]");
}

function fitClass(fit: number | null): string {
  if (fit == null) return "text-dim";
  if (fit >= 0.8) return "text-green";
  if (fit >= 0.6) return "text-amber";
  return "text-red";
}

function applyFilters(clients: BookClient[], p: ClientBookProps): BookClient[] {
  let out = clients;
  if (p.mandate) out = out.filter((c) => c.mandate.toLowerCase() === p.mandate!.toLowerCase());
  if (p.hasConflicts) out = out.filter((c) => c.conflict_positions > 0);
  if (p.minFit != null)
    out = out.filter((c) => c.portfolio_fit != null && c.portfolio_fit * 100 >= p.minFit!);
  if (p.maxFit != null)
    out = out.filter((c) => c.portfolio_fit != null && c.portfolio_fit * 100 <= p.maxFit!);

  const sorted = [...out];
  switch (p.sortBy) {
    case "fit_asc":
      sorted.sort((a, b) => (a.portfolio_fit ?? 1) - (b.portfolio_fit ?? 1));
      break;
    case "conflicts_desc":
      sorted.sort((a, b) => b.conflict_positions - a.conflict_positions);
      break;
    case "name":
      sorted.sort((a, b) => a.client_name.localeCompare(b.client_name));
      break;
    case "fit_desc":
    default:
      sorted.sort((a, b) => (b.portfolio_fit ?? 0) - (a.portfolio_fit ?? 0));
  }
  return sorted;
}

// Human-readable summary of the active filter, for the header + empty state.
function filterSummary(p: ClientBookProps): string | null {
  const parts: string[] = [];
  if (p.mandate) parts.push(`${p.mandate} mandate`);
  if (p.hasConflicts) parts.push("with conflicts");
  if (p.minFit != null) parts.push(`fit ≥ ${Math.round(p.minFit)}`);
  if (p.maxFit != null) parts.push(`fit ≤ ${Math.round(p.maxFit)}`);
  return parts.length ? parts.join(" · ") : null;
}

export function ClientBook(props: ClientBookProps) {
  const { addSpecs, openClient } = useCanvasActions();
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  // Server already supports ?mandate=; pass it through, filter the rest client-side.
  useEffect(() => {
    setStatus({ kind: "loading" });
    const ctrl = new AbortController();
    getBook(props.mandate ?? undefined, ctrl.signal)
      .then((res) => {
        if (!ctrl.signal.aborted)
          setStatus({ kind: "ok", clients: res.clients.filter(isRealClient) });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setStatus({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, [props.mandate]);

  const summary = filterSummary(props);
  const filtered = status.kind === "ok" ? applyFilters(status.clients, props) : [];

  return (
    <WidgetContainer
      title={props.title?.trim() || "Client Book"}
      source="CRM & Portfolio Systems"
      badges={
        status.kind === "ok" ? (
          <span className="rounded-full bg-panel3 px-2 py-0.5 text-[10px] font-medium text-muted">
            {filtered.length}
          </span>
        ) : undefined
      }
    >
      {summary && (
        <div className="mb-3 text-[11px] text-dim">
          Filtered: <span className="text-muted">{summary}</span>
        </div>
      )}

      {status.kind === "loading" ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded bg-panel2" />
          ))}
        </div>
      ) : status.kind === "error" ? (
        <div>
          <p className="text-[13px] text-muted">Could not load the client book.</p>
          <p className="mt-1 text-[11px] text-dim">{status.message}</p>
        </div>
      ) : filtered.length === 0 ? (
        <p className="text-[13px] text-muted">
          {summary ? `No clients match this filter (${summary}).` : "No clients in the book yet."}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full whitespace-nowrap text-left text-sm">
            <thead>
              <tr className="border-b border-border text-dim">
                <th className="pb-3 font-medium">Client</th>
                <th className="pb-3 font-medium">Mandate</th>
                <th className="pb-3 font-medium">Holdings</th>
                <th className="pb-3 font-medium">Fit</th>
                <th className="pb-3 font-medium">Conflicts</th>
                <th className="pb-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((c) => (
                <tr key={c.client_id} className="transition-colors hover:bg-panel2/40">
                  <td className="py-4 font-medium text-text">{c.client_name}</td>
                  <td className="py-4">
                    <span className="rounded-md border border-border bg-panel2 px-2 py-1 text-xs text-muted">
                      {c.mandate}
                    </span>
                  </td>
                  <td className="py-4 text-muted">{c.total_positions}</td>
                  <td className="py-4">
                    <div className="flex items-center gap-2">
                      <span className={fitClass(c.portfolio_fit)}>
                        {c.portfolio_fit != null ? Math.round(c.portfolio_fit * 100) : "—"}
                      </span>
                      <TrendingUp className="h-3 w-3 text-dim" />
                    </div>
                  </td>
                  <td className="py-4">
                    <span className={c.conflict_positions > 0 ? "text-red" : "text-muted"}>
                      {c.conflict_positions}
                    </span>
                  </td>
                  <td className="py-4 text-right">
                    <button
                      type="button"
                      onClick={() =>
                        // Honor an explicit openComponent override; otherwise open
                        // the client in the RM's preferred default view.
                        props.openComponent
                          ? addSpecs([
                              {
                                component: props.openComponent,
                                props: { clientId: c.client_id },
                              },
                            ])
                          : openClient(c.client_id)
                      }
                      className="rounded bg-panel2 p-1.5 text-muted transition-colors hover:bg-panel3 hover:text-text"
                      aria-label={`Open ${c.client_name}`}
                    >
                      <ArrowRight className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </WidgetContainer>
  );
}
