interface Citation {
  source: string;
  text: string;
}

interface TaskResultCardProps {
  clientId: string;
  taskTitle?: string | null;
  summary?: string;
  citations?: Citation[];
  onViewClient?: (clientId: string) => void;
}

export function TaskResultCard({
  clientId,
  taskTitle,
  summary,
  citations,
  onViewClient,
}: TaskResultCardProps) {
  return (
    <div className="rounded-[14px] border border-border bg-panel p-4 space-y-3">
      <div className="flex items-start gap-2">
        <span className="shrink-0 rounded-md border border-violet/30 bg-violet/10 px-1.5 py-0.5 text-[10px] font-semibold text-violet">
          Task Result
        </span>
        {taskTitle && (
          <p className="flex-1 text-[13px] font-medium text-text leading-snug">
            {taskTitle}
          </p>
        )}
      </div>

      <div className="text-[12.5px] leading-relaxed text-muted">
        {summary ? (
          summary
        ) : (
          <span className="text-dim italic">No summary available.</span>
        )}
      </div>

      {citations && citations.length > 0 && (
        <div className="space-y-1 border-t border-border pt-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-dim">
            Sources
          </p>
          {citations.map((c, i) => (
            <div key={i} className="flex gap-1.5 text-[11px]">
              <span className="shrink-0 font-medium text-muted">{c.source}</span>
              <span className="text-dim">—</span>
              <span className="text-muted">{c.text}</span>
            </div>
          ))}
        </div>
      )}

      {onViewClient && (
        <button
          type="button"
          onClick={() => onViewClient(clientId)}
          className="text-[11px] font-medium text-blue transition-colors hover:text-blue/80"
        >
          View client →
        </button>
      )}
    </div>
  );
}
