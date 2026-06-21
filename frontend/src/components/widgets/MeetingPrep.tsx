import { useEffect, useState } from "react";
import { getClientDna, type DnaResponse } from "../../api/dna";
import { WidgetContainer } from "./WidgetContainer";

// Ported from Kielis_Advisor_workbech MeetingPrepCanvas, re-tokenised and wired
// to live DNA. The agenda is generated from the client's actual DNA (life events,
// open promises, values) — items only appear when the data exists; nothing is
// fabricated. Key Facts come straight from the DNA profile.

type Status =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; dna: DnaResponse };

interface AgendaItem {
  title: string;
  detail: string;
}

function texts(items: { text: string }[] | null | undefined): string[] {
  return (items ?? []).map((i) => i.text).filter(Boolean);
}

function buildAgenda(dna: DnaResponse): AgendaItem[] {
  const agenda: AgendaItem[] = [];
  const life = texts(dna.life_events);
  const promises = texts(dna.promises);
  const values = texts(dna.values);
  const exclusions = texts(dna.exclusions);

  if (life.length) {
    agenda.push({ title: "Life Event Check-in", detail: life.slice(0, 2).join("; ") });
  }
  if (promises.length) {
    agenda.push({ title: "Open Promises", detail: promises.slice(0, 3).join("; ") });
  }
  if (values.length || exclusions.length) {
    const parts = [
      values.length ? `Reaffirm priorities: ${values.slice(0, 3).join(", ")}` : "",
      exclusions.length ? `Confirm red lines: ${exclusions.slice(0, 2).join(", ")}` : "",
    ].filter(Boolean);
    agenda.push({ title: "Values & Portfolio Alignment", detail: parts.join(". ") });
  }
  return agenda;
}

interface MeetingPrepProps {
  clientId: string;
}

export function MeetingPrep({ clientId }: MeetingPrepProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    setStatus({ kind: "loading" });
    const ctrl = new AbortController();
    getClientDna(clientId, ctrl.signal)
      .then((dna) => {
        if (!ctrl.signal.aborted) setStatus({ kind: "ok", dna });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setStatus({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, [clientId]);

  if (status.kind === "loading") {
    return <div className="h-64 animate-pulse rounded-2xl bg-panel2" />;
  }
  if (status.kind === "error") {
    return (
      <WidgetContainer title="Meeting Prep" source="CRM">
        <p className="text-[13px] text-muted">Could not load meeting prep.</p>
        <p className="mt-1 text-[11px] text-dim">{status.message}</p>
      </WidgetContainer>
    );
  }

  const { dna } = status;
  const agenda = buildAgenda(dna);
  const redLines = texts(dna.exclusions);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-text">
          Meeting Prep: {dna.client_name}
        </h2>
        <p className="text-sm text-muted">{dna.mandate ?? "—"} mandate</p>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <WidgetContainer title="Suggested Agenda" className="flex-1" source="AI Planner">
          {agenda.length ? (
            <ul className="space-y-4">
              {agenda.map((item, i) => (
                <li key={item.title} className="flex items-start gap-4">
                  <div className="mt-0.5 font-mono text-blue">{String(i + 1).padStart(2, "0")}</div>
                  <div>
                    <h4 className="font-medium text-text">{item.title}</h4>
                    <p className="mt-1 text-sm text-muted">{item.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              Not enough DNA captured yet to suggest an agenda for this client.
            </p>
          )}
        </WidgetContainer>

        <div className="w-full shrink-0 lg:w-[300px]">
          <WidgetContainer title="Key Facts" source="CRM">
            <div className="space-y-3 text-sm text-muted">
              <div>
                <span className="text-dim">Mandate: </span>
                <span className="text-text">{dna.mandate ?? "—"}</span>
              </div>
              <div>
                <span className="text-dim">Temperament: </span>
                <span className="text-text">{dna.temperament || "—"}</span>
              </div>
              <div>
                <span className="text-dim">Red Lines: </span>
                <span className="text-text">{redLines.length ? redLines.join(", ") : "—"}</span>
              </div>
            </div>
          </WidgetContainer>
        </div>
      </div>
    </div>
  );
}
