import { useEffect, useState } from "react";
import { getHealth } from "../../api/health";

// Backend connectivity chip (TASK-003, AC #3). Polls GET /health on mount and
// surfaces loading / ok / error states — also a live proof that CORS works.

type Status =
  | { kind: "loading" }
  | { kind: "ok"; environment: string }
  | { kind: "error" };

export function BackendStatus() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    getHealth(ctrl.signal)
      .then((h) => setStatus({ kind: "ok", environment: h.environment }))
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setStatus({ kind: "error" });
        console.warn("backend /health unreachable:", err);
      });
    return () => ctrl.abort();
  }, []);

  const { dot, label, title } = describe(status);

  return (
    <span
      title={title}
      className="hidden items-center gap-1.5 rounded-full border border-border bg-panel2 px-2.5 py-1 text-[11px] text-muted sm:inline-flex"
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  );
}

function describe(status: Status): {
  dot: string;
  label: string;
  title: string;
} {
  switch (status.kind) {
    case "ok":
      return {
        dot: "bg-green",
        label: `API · ${status.environment}`,
        title: "Backend /health: ok",
      };
    case "error":
      return {
        dot: "bg-red",
        label: "API offline",
        title: "Backend /health unreachable",
      };
    case "loading":
    default:
      return {
        dot: "bg-amber",
        label: "API…",
        title: "Checking backend /health…",
      };
  }
}
