import { useState } from "react";
import type { DnaSource } from "../../api/dna";

function sortedByDateDesc(sources: DnaSource[]): DnaSource[] {
  return [...sources].sort((a, b) => {
    if (!a.date && !b.date) return 0;
    if (!a.date) return 1;
    if (!b.date) return -1;
    return b.date.localeCompare(a.date);
  });
}

function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-CH", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function mediumLabel(medium: string | null): string {
  if (!medium) return "—";
  const m = medium.toLowerCase();
  if (m.includes("phone") || m.includes("call")) return "CALL";
  if (m.includes("email")) return "EMAIL";
  if (m.includes("meet")) return "MEETING";
  return medium.toUpperCase().slice(0, 6);
}

interface RelationshipTimelineProps {
  sources: DnaSource[];
}

export function RelationshipTimeline({ sources }: RelationshipTimelineProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (sources.length === 0) {
    return (
      <div className="py-6 text-center text-[13px] text-dim">
        No CRM sources linked to this DNA profile.
      </div>
    );
  }

  const sorted = sortedByDateDesc(sources);

  return (
    <div className="space-y-0">
      {sorted.map((s) => {
        const isExpanded = expandedId === s.id;
        const isLong = (s.note?.length ?? 0) > 120;
        const displayNote =
          isExpanded || !isLong ? (s.note ?? "—") : s.note!.slice(0, 120) + "…";

        return (
          <div key={s.id} className="border-l border-border pl-3 pb-4 last:pb-0">
            <div className="flex items-center gap-2 mb-1">
              <time
                dateTime={s.date ?? undefined}
                className="text-[11px] font-mono text-muted"
              >
                {s.date ? formatDate(s.date) : "—"}
              </time>
              <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold bg-panel3 text-dim border border-border">
                {mediumLabel(s.medium)}
              </span>
            </div>
            <p className="text-[13px] text-text leading-snug">{displayNote}</p>
            {isLong && (
              <button
                type="button"
                onClick={() => setExpandedId(isExpanded ? null : s.id)}
                className="mt-1 text-[11px] text-muted hover:text-text transition-colors"
              >
                {isExpanded ? "▲ Collapse" : "▼ Show full note"}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
