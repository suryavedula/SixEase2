import { useState, useEffect } from "react";
import { getClientDna } from "../../api/dna";
import type { DnaItem, DnaResponse, DnaSource } from "../../api/dna";
import { SourcesFooter, dnaSourceToDisplaySource } from "./SourcesFooter";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: DnaResponse }
  | { kind: "error"; message: string };

function buildSourceMap(sources: DnaSource[]): Map<string, DnaSource> {
  return new Map(sources.map((s) => [s.id, s]));
}

function confidenceDot(confidence: number): string {
  if (confidence >= 0.85) return "text-green";
  if (confidence >= 0.65) return "text-amber";
  return "text-dim";
}

function mandateBadgeClass(mandate: string): string {
  const m = mandate.toUpperCase();
  if (m === "BALANCED") return "bg-blue/10 text-blue border-blue/20";
  if (m === "GROWTH") return "bg-green/10 text-green border-green/20";
  if (m === "DEFENSIVE") return "bg-purple/10 text-purple border-purple/20";
  return "bg-panel3 text-muted border-border";
}

interface ItemSectionProps {
  label: string;
  items: DnaItem[];
  section: string;
  chipClass: string;
  expandedItem: string | null;
  onToggle: (key: string | null) => void;
  sourceMap: Map<string, DnaSource>;
}

function ItemSection({
  label,
  items,
  section,
  chipClass,
  expandedItem,
  onToggle,
  sourceMap,
}: ItemSectionProps) {
  if (items.length === 0) return null;

  return (
    <div className="mb-3">
      <p className="text-[11px] font-semibold text-dim uppercase tracking-wider mb-1.5">
        {label}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item, i) => {
          const key = `${section}:${i}`;
          const isOpen = expandedItem === key;
          const chipLabel = item.tag ?? item.text.slice(0, 40);

          return (
            <div key={i}>
              <button
                type="button"
                title={item.text}
                onClick={() => onToggle(isOpen ? null : key)}
                className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[12px] transition-colors ${chipClass} ${isOpen ? "ring-1 ring-current" : ""}`}
              >
                <span className={`text-[8px] ${confidenceDot(item.confidence)}`}>●</span>
                {chipLabel}
              </button>
              {isOpen && item.source_note_ids.length > 0 && (
                <div className="mt-1.5 rounded-lg border border-border bg-panel2 p-2.5 text-[12px]">
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-dim">
                    Sources
                  </p>
                  {item.source_note_ids.map((sid) => {
                    const src = sourceMap.get(sid);
                    if (!src) return null;
                    return (
                      <div key={sid} className="mb-1.5 last:mb-0 text-muted leading-snug">
                        <span className="font-mono text-[10px] text-dim">
                          {src.date ?? "—"} · {src.medium ?? "—"}
                        </span>
                        <p className="mt-0.5">{src.note?.slice(0, 160) ?? "—"}</p>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface DnaCardProps {
  clientId: string;
}

export function DnaCard({ clientId }: DnaCardProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [expandedItem, setExpandedItem] = useState<string | null>(null);

  useEffect(() => {
    setStatus({ kind: "loading" });
    const ctrl = new AbortController();
    getClientDna(clientId, ctrl.signal)
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
        <div className="h-5 w-40 animate-pulse rounded bg-panel3" />
        <div className="h-3 w-full animate-pulse rounded bg-panel3" />
        <div className="h-3 w-3/4 animate-pulse rounded bg-panel3" />
      </div>
    );
  }

  if (status.kind === "error") {
    const is404 = status.message.includes("404");
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px]">
        {is404 ? (
          <p className="text-muted">
            DNA not yet extracted — run{" "}
            <code className="font-mono text-dim">POST /admin/seed/dna</code> to populate.
          </p>
        ) : (
          <>
            <p className="text-muted">Could not load DNA.</p>
            <p className="mt-1 text-dim text-[11px]">{status.message}</p>
          </>
        )}
      </div>
    );
  }

  const { data } = status;
  const sourceMap = buildSourceMap(data.sources);

  return (
    <div className="rounded-[14px] border border-border bg-panel p-4">
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[18px]">◆</span>
        <span className="font-semibold text-[15px] text-text flex-1">{data.client_name}</span>
        {data.mandate && (
          <span
            className={`rounded border px-2 py-0.5 text-[11px] font-semibold ${mandateBadgeClass(data.mandate)}`}
          >
            {data.mandate}
          </span>
        )}
        <span className="text-[11px] text-dim font-mono">v{data.version}</span>
      </div>

      {/* One-liner */}
      {data.temperament && (
        <p className="mb-3 text-[13px] italic text-muted line-clamp-2">{data.temperament}</p>
      )}

      {/* Sections */}
      <ItemSection
        label="Values"
        items={data.values ?? []}
        section="values"
        chipClass="bg-blue/10 text-blue border-blue/20"
        expandedItem={expandedItem}
        onToggle={setExpandedItem}
        sourceMap={sourceMap}
      />
      <ItemSection
        label="Exclusions"
        items={data.exclusions ?? []}
        section="exclusions"
        chipClass="bg-red/10 text-red border-red/20"
        expandedItem={expandedItem}
        onToggle={setExpandedItem}
        sourceMap={sourceMap}
      />
      <ItemSection
        label="Tilts"
        items={data.tilts ?? []}
        section="tilts"
        chipClass="bg-amber/10 text-amber border-amber/20"
        expandedItem={expandedItem}
        onToggle={setExpandedItem}
        sourceMap={sourceMap}
      />
      <ItemSection
        label="Promises"
        items={data.promises ?? []}
        section="promises"
        chipClass="bg-teal/10 text-teal border-teal/20"
        expandedItem={expandedItem}
        onToggle={setExpandedItem}
        sourceMap={sourceMap}
      />

      {/* Life events */}
      {data.life_events && data.life_events.length > 0 && (
        <div className="mb-3">
          <p className="text-[11px] font-semibold text-dim uppercase tracking-wider mb-1.5">
            Life Events
          </p>
          <ul className="space-y-1">
            {data.life_events.map((ev, i) => (
              <li key={i} className="text-[13px] text-text leading-snug">
                <span className="text-dim mr-1.5">—</span>
                {ev.text}
              </li>
            ))}
          </ul>
        </div>
      )}

      <SourcesFooter sources={data.sources.map(dnaSourceToDisplaySource)} />
    </div>
  );
}
