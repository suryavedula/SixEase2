import { useEffect, useState } from "react";
import { chfCompact } from "../../lib/format";
import { ShieldAlert, Target, User, Activity } from "lucide-react";
import { getClientDna, type DnaResponse } from "../../api/dna";
import {
  getPortfolioAllocation,
  getPortfolioFit,
  type AllocationResponse,
  type PortfolioFitResponse,
} from "../../api/portfolio";
import { useCanvasActions } from "../shell/CanvasActions";
import { WidgetContainer } from "./WidgetContainer";

// Ported from Kielis_Advisor_workbech Client360Canvas, re-tokenised onto our
// theme and wired to live data: DNA (values/red-lines/context/life-events) +
// portfolio fit/allocation for the health strip. "Deep Dive Portfolio" appends
// the PortfolioView widget to the canvas instead of switching a template.

type Status =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; dna: DnaResponse; fit: PortfolioFitResponse | null; alloc: AllocationResponse | null };

const RISK_BY_MANDATE: Record<string, string> = {
  DEFENSIVE: "Low",
  BALANCED: "Medium",
  GROWTH: "High",
};

function texts(items: { text: string }[] | null | undefined, n = 8): string[] {
  return (items ?? []).map((i) => i.text).filter(Boolean).slice(0, n);
}

interface Client360Props {
  clientId: string;
}

export function Client360({ clientId }: Client360Props) {
  const { addSpecs } = useCanvasActions();
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    setStatus({ kind: "loading" });
    const ctrl = new AbortController();
    // DNA is required; fit + allocation enrich the health strip and degrade to null.
    getClientDna(clientId, ctrl.signal)
      .then(async (dna) => {
        const [fit, alloc] = await Promise.all([
          getPortfolioFit(clientId, ctrl.signal).catch(() => null),
          getPortfolioAllocation(clientId, ctrl.signal).catch(() => null),
        ]);
        if (!ctrl.signal.aborted) setStatus({ kind: "ok", dna, fit, alloc });
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
        <div className="h-6 w-48 animate-pulse rounded bg-panel3" />
        <div className="grid gap-4 lg:grid-cols-12">
          <div className="h-48 animate-pulse rounded-2xl bg-panel2 lg:col-span-4" />
          <div className="h-48 animate-pulse rounded-2xl bg-panel2 lg:col-span-8" />
        </div>
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <WidgetContainer title="Client 360" source="CRM">
        <p className="text-[13px] text-muted">Could not load client profile.</p>
        <p className="mt-1 text-[11px] text-dim">{status.message}</p>
      </WidgetContainer>
    );
  }

  const { dna, fit, alloc } = status;
  const mandate = dna.mandate ?? "—";
  const risk = RISK_BY_MANDATE[mandate.toUpperCase()] ?? "—";
  const values = texts(dna.values);
  const tilts = texts(dna.tilts);
  const redLines = texts(dna.exclusions);
  const lifeEvents = texts(dna.life_events);
  const context = dna.family_context || dna.business_context || "—";

  const fitScore = fit?.portfolio_fit != null ? Math.round(fit.portfolio_fit * 100) : null;
  const totalValue = alloc?.total_chf ?? null;
  const maxDrift = alloc?.sac_rows?.length
    ? Math.max(...alloc.sac_rows.map((r) => Math.abs(r.drift_pp)))
    : null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-text">{dna.client_name} — Snapshot</h2>
        <p className="text-sm text-muted">{mandate} mandate</p>
      </div>

      <div className="flex flex-col gap-6 lg:grid lg:grid-cols-12">
        {/* Client Profile */}
        <WidgetContainer title="Client Profile" className="lg:col-span-4" source="CRM">
          <div className="space-y-1 text-sm">
            <Row label="Total Value" value={totalValue != null ? `CHF ${chfCompact(totalValue)}` : "—"} />
            <Row label="Risk Profile" value={risk} />
            <Row label="Mandate" value={mandate} />
            <Row label="Temperament" value={dna.temperament || "—"} last />
          </div>
        </WidgetContainer>

        {/* Client DNA */}
        <WidgetContainer title="Client DNA" className="lg:col-span-8" source="Synthesised Identity">
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div>
              <SectionLabel icon={<Target className="h-3 w-3" />}>Core Values &amp; Preferences</SectionLabel>
              <div className="mb-4 flex flex-wrap gap-2">
                {values.map((v) => (
                  <span key={v} className="rounded border border-blue/20 bg-blue/10 px-2 py-1 text-xs text-blue">
                    {v}
                  </span>
                ))}
                {tilts.map((v) => (
                  <span key={v} className="rounded border border-border bg-panel3 px-2 py-1 text-xs text-muted">
                    {v}
                  </span>
                ))}
                {values.length === 0 && tilts.length === 0 && <Empty />}
              </div>

              <SectionLabel icon={<ShieldAlert className="h-3 w-3" />} tone="red">Red Lines</SectionLabel>
              <ul className="space-y-2">
                {redLines.length ? (
                  redLines.map((r) => (
                    <li key={r} className="flex items-start gap-2 text-sm text-text">
                      <span className="mt-1 text-red">•</span> {r}
                    </li>
                  ))
                ) : (
                  <Empty />
                )}
              </ul>
            </div>

            <div>
              <SectionLabel icon={<User className="h-3 w-3" />}>Context</SectionLabel>
              <p className="mb-4 text-sm leading-relaxed text-muted">{context}</p>

              <SectionLabel icon={<Activity className="h-3 w-3" />}>Life Events</SectionLabel>
              <ul className="space-y-2">
                {lifeEvents.length ? (
                  lifeEvents.map((e) => (
                    <li key={e} className="flex items-start gap-2 text-sm text-text">
                      <span className="mt-1 text-blue">•</span> {e}
                    </li>
                  ))
                ) : (
                  <Empty />
                )}
              </ul>
            </div>
          </div>
        </WidgetContainer>
      </div>

      {/* Portfolio Health strip */}
      <WidgetContainer
        title="Portfolio Health"
        source="Portfolio Engine"
        badges={
          fitScore != null ? (
            <span className="rounded-full bg-green/20 px-2 text-[10px] font-bold uppercase tracking-wider text-green">
              Fit Score: {fitScore}
            </span>
          ) : undefined
        }
      >
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div className="flex gap-4 sm:gap-12">
            <div>
              <div className="mb-1 text-xs text-dim">Total Value</div>
              <div className="text-xl font-semibold text-text sm:text-2xl">
                {totalValue != null ? `CHF ${chfCompact(totalValue)}` : "—"}
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs text-dim">Max Drift</div>
              <div className="text-xl font-semibold text-amber sm:text-2xl">
                {maxDrift != null ? `${maxDrift.toFixed(1)}pp` : "—"}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => addSpecs([{ component: "PortfolioView", props: { clientId } }])}
            className="w-full rounded-lg bg-panel2 px-4 py-2 text-sm font-medium text-text transition-colors hover:bg-panel3 sm:w-auto"
          >
            Deep Dive Portfolio
          </button>
        </div>
      </WidgetContainer>
    </div>
  );
}

function Row({ label, value, last }: { label: string; value: string; last?: boolean }) {
  return (
    <div className={`flex justify-between py-2 ${last ? "" : "border-b border-border"}`}>
      <span className="text-dim">{label}</span>
      <span className="text-text">{value}</span>
    </div>
  );
}

function SectionLabel({
  icon,
  children,
  tone,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
  tone?: "red";
}) {
  return (
    <h4
      className={`mb-3 mt-6 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider first:mt-0 ${
        tone === "red" ? "text-red" : "text-muted"
      }`}
    >
      {icon} {children}
    </h4>
  );
}

function Empty() {
  return <span className="text-xs text-dim">None recorded.</span>;
}
