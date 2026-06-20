// Central conversation canvas (TASK-003, TASK-041, TASK-043). Renders the
// interleaved transcript of chat bubbles and generative-UI widgets from the
// WidgetSpec list. Auto-scrolls to the newest turn. Empty state invites a query.

import { useEffect, useRef } from "react";
import { WidgetRenderer } from "../../registry/WidgetRenderer";
import type { WidgetSpec } from "../../registry/types";

interface CanvasProps {
  specs: WidgetSpec[];
  onClearSpecs: () => void;
}

export function Canvas({ specs, onClearSpecs }: CanvasProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Keep the latest turn in view as the conversation grows.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [specs.length]);

  if (specs.length === 0) {
    return (
      <main className="h-full overflow-auto p-[18px]">
        <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-border bg-panel2 text-2xl">
            ◆
          </div>
          <h1 className="mb-1 text-[22px] font-semibold tracking-tight">
            Ask your workbench
          </h1>
          <p className="max-w-md text-[14px] text-muted">
            Have a conversation — ask about a client, their portfolio, or what
            needs your attention. Answers and live views are generated here as
            you talk.
          </p>
          <p className="mt-3 text-[12px] text-dim">
            Try{" "}
            <code className="font-mono text-muted">
              How does Schneider's portfolio fit her values?
            </code>{" "}
            or <code className="font-mono text-muted">/client Schneider</code>
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="h-full overflow-auto p-[18px]">
      <div className="mx-auto max-w-3xl space-y-4">
        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={onClearSpecs}
            className="text-[12px] text-muted transition-colors hover:text-text"
          >
            × clear canvas
          </button>
        </div>
        {specs.map((spec, i) => (
          <WidgetRenderer key={i} spec={spec} />
        ))}
        <div ref={bottomRef} />
      </div>
    </main>
  );
}
