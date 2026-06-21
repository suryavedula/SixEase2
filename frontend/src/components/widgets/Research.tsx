import { Search } from "lucide-react";
import { useCanvasActions } from "../shell/CanvasActions";
import { WidgetContainer } from "./WidgetContainer";

// Ported from Kielis_Advisor_workbech ResearchTaskCanvas, re-tokenised. Renders
// the result of an autonomous research task. Data-honest: only the query,
// summary, and real sources are shown — no fabricated "sources checked / confidence"
// stat tiles. Driven by inline props from AppShell's task-promote handler.

interface Citation {
  source: string;
  text: string;
}

interface Recommendation {
  security?: string;
  issuer?: string;
  isin?: string;
  industry_group?: string;
  region?: string;
  cio_view?: string;
  reason?: string;
}

interface ResearchProps {
  clientId?: string;
  taskTitle?: string | null;
  summary?: string;
  citations?: Citation[];
  recommendations?: Recommendation[];
  provenance?: { notes_read?: number; articles_fetched?: number };
}

export function Research({ clientId, taskTitle, summary, citations, recommendations, provenance }: ResearchProps) {
  const { addSpecs } = useCanvasActions();
  const provLabel = provenance
    ? [
        provenance.notes_read != null ? `${provenance.notes_read} CRM notes` : null,
        provenance.articles_fetched != null
          ? `${provenance.articles_fetched} news articles`
          : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";

  return (
    <WidgetContainer
      title="Autonomous Research Brief"
      source="AI Research Agent"
      badges={
        <span className="rounded-full bg-blue/20 px-2 text-[10px] font-bold uppercase tracking-wider text-blue">
          Completed
        </span>
      }
    >
      <div className="space-y-6">
        <div>
          <h3 className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wider text-dim">
            <Search className="h-3 w-3" /> Query
          </h3>
          <p className="text-base text-text">{taskTitle || "Research task"}</p>
        </div>

        <div>
          <h3 className="mb-1 text-xs uppercase tracking-wider text-dim">Findings</h3>
          {summary ? (
            <p className="text-sm leading-relaxed text-muted">{summary}</p>
          ) : (
            <p className="text-sm italic text-dim">No summary available for this task.</p>
          )}
          {provLabel && (
            <p className="mt-2 text-[11px] uppercase tracking-wider text-dim">
              Grounded in {provLabel}
            </p>
          )}
        </div>

        {recommendations && recommendations.length > 0 && (
          <div>
            <h3 className="mb-3 text-xs uppercase tracking-wider text-dim">
              Recommended instruments
              <span className="ml-2 text-[10px] normal-case text-dim">CIO BUY · matched to client values</span>
            </h3>
            <div className="space-y-3">
              {recommendations.map((r, i) => (
                <div key={i} className="rounded-lg border border-border bg-panel2/50 p-3">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-semibold text-text">
                      {[r.issuer, r.security].filter(Boolean).join(" — ") || "Instrument"}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-dim">{r.isin}</span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-dim">
                    {[r.industry_group, r.region].filter(Boolean).join(" · ")}
                  </div>
                  {r.reason && (
                    <p className="mt-1.5 text-xs leading-relaxed text-muted">{r.reason}</p>
                  )}
                  {r.cio_view && (
                    <p className="mt-1 text-[11px] italic leading-relaxed text-dim">
                      CIO: {r.cio_view}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {citations && citations.length > 0 && (
          <div>
            <h3 className="mb-3 text-xs uppercase tracking-wider text-dim">Sources</h3>
            <div className="space-y-3">
              {citations.map((c, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-border bg-panel2/50 p-3 text-sm"
                >
                  <div className="font-medium text-text">{c.source}</div>
                  <div className="mt-1 text-xs text-muted">{c.text}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {clientId && (
          <button
            type="button"
            onClick={() => addSpecs([{ component: "Client360", props: { clientId } }])}
            className="text-[12px] font-medium text-blue transition-colors hover:text-blue/80"
          >
            Open client →
          </button>
        )}
      </div>
    </WidgetContainer>
  );
}
