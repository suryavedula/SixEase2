import { useState } from "react";
import type { DnaSource } from "../../api/dna";

export type SourceKind = "CRM" | "NEWS" | "CIO" | "MANDATE";

export interface DisplaySource {
  id: string;
  kind: SourceKind;
  label: string;
  detail: string | null;
  url: string | null;
  date: string | null;
}

const KIND_CLASSES: Record<SourceKind, string> = {
  CRM: "bg-blue/10 text-blue border-blue/20",
  NEWS: "bg-amber/10 text-amber border-amber/20",
  CIO: "bg-teal/10 text-teal border-teal/20",
  MANDATE: "bg-panel3 text-dim border-border",
};

function KindBadge({ kind }: { kind: SourceKind }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${KIND_CLASSES[kind]}`}>
      {kind}
    </span>
  );
}

export function dnaSourceToDisplaySource(src: DnaSource): DisplaySource {
  return {
    id: src.id,
    kind: "CRM",
    label: src.medium ?? "CRM Note",
    detail: src.note?.slice(0, 200) ?? null,
    url: null,
    date: src.date,
  };
}

export function SourcesFooter({
  sources,
  initialOpen = false,
}: {
  sources: DisplaySource[];
  initialOpen?: boolean;
}) {
  const [open, setOpen] = useState(initialOpen);

  if (sources.length === 0) return null;

  return (
    <div className="mt-3 border-t border-border pt-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-[12px] text-muted hover:text-text transition-colors"
      >
        {open ? "▲" : "▼"} Sources ({sources.length})
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          {sources.map((src) => (
            <div key={src.id} className="border-l-2 border-border pl-3">
              <div className="flex items-center gap-2 mb-0.5">
                <KindBadge kind={src.kind} />
                {src.date && (
                  <time className="text-[11px] font-mono text-muted">{src.date}</time>
                )}
              </div>
              <p className="text-[13px] text-text leading-snug">{src.label}</p>
              {src.detail && (
                <p className="mt-0.5 text-[12px] text-muted leading-snug">{src.detail}</p>
              )}
              {src.url && (
                <a
                  href={src.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-0.5 inline-block text-[11px] text-blue hover:underline"
                >
                  View source →
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
