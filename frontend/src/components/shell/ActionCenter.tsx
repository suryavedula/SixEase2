import { useState } from "react";
import type { AlertWithClient } from "../../api/alerts";
import type { TaskWithClient } from "../../api/tasks";
import { TasksList } from "../widgets/TasksList";

const CATEGORIES = [
  "All",
  "Urgent",
  "Clients",
  "Market",
  "Compliance",
  "Tasks",
] as const;
type Category = (typeof CATEGORIES)[number];

const CLASS_TO_CATEGORY: Record<string, Category> = {
  quiet_client: "Clients",
  overdue_promise: "Clients",
  good_news: "Clients",
  dna_conflict: "Compliance",
  values_drift: "Compliance",
  behavioural_guardrail: "Compliance",
  news_impact: "Market",
  panic: "Market",
  drift_breach: "Market",
  stale_sell: "Market",
};

const SEVERITY_CHIP: Record<string, string> = {
  Critical: "bg-red/10 text-red border-red/30",
  Attention: "bg-amber/10 text-amber border-amber/30",
  FYI: "bg-blue/10 text-blue border-blue/30",
};

const ACTION_LABEL: Record<string, string> = {
  Trade: "Rebalance",
  ReachOut: "Draft Message",
  Acknowledge: "Acknowledge",
  Watch: "Watch",
};

function alertAge(iso: string): string {
  const h = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
  if (h < 1) return "<1h";
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function matchesCategory(alert: AlertWithClient, cat: Category): boolean {
  if (cat === "All") return true;
  if (cat === "Urgent") return alert.severity === "Critical";
  if (cat === "Tasks")
    return alert.action_type === "Trade" || alert.action_type === "ReachOut";
  const mapped = CLASS_TO_CATEGORY[alert.alert_class ?? ""] ?? "Market";
  return mapped === cat;
}

interface ActionCenterProps {
  open: boolean;
  alerts: AlertWithClient[];
  tasks: TaskWithClient[];
  alertCount: number;
  onOpenClient: (clientId: string) => void;
  onDismiss: (id: string) => void;
  onMarkAllRead: () => void;
  onTaskAssign?: (task: TaskWithClient) => void;
  onTaskPromote?: (task: TaskWithClient) => void;
  onTaskDiscard?: (task: TaskWithClient) => void;
}

export function ActionCenter({
  open,
  alerts,
  tasks,
  alertCount,
  onOpenClient,
  onDismiss,
  onMarkAllRead,
  onTaskAssign,
  onTaskPromote,
  onTaskDiscard,
}: ActionCenterProps) {
  const [activeCategory, setActiveCategory] = useState<Category>("All");

  if (!open) return null;

  const visible = alerts.filter((a) => matchesCategory(a, activeCategory));

  return (
    <aside className="flex h-full flex-col overflow-hidden border-l border-border bg-panel2/40 lg:bg-[var(--color-bg)]">
      <div className="flex items-center gap-2 px-3.5 py-3">
        <span className="text-[14px] font-semibold">Action Center</span>
        {alertCount > 0 && (
          <span className="flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red px-1 text-[10px] font-semibold text-white">
            {alertCount > 99 ? "99+" : alertCount}
          </span>
        )}
        <button
          type="button"
          onClick={onMarkAllRead}
          className="ml-auto text-[11px] text-muted transition-colors hover:text-text"
        >
          Mark all read
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5 px-3.5 pb-3">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            type="button"
            onClick={() => setActiveCategory(cat)}
            className={`rounded-lg border px-2 py-1 text-[11px] transition-colors ${
              activeCategory === cat
                ? "border-blue/40 bg-blue/10 text-blue"
                : "border-border text-muted hover:text-text"
            }`}
          >
            {cat}
            {cat === "Tasks" && tasks.length > 0 && (
              <span className="ml-1 rounded-full bg-violet/20 px-1 text-[9px] font-semibold text-violet">
                {tasks.length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto space-y-2 px-3.5 pb-4">
        {activeCategory === "Tasks" ? (
          <TasksList
            tasks={tasks}
            onOpenClient={onOpenClient}
            onAssign={onTaskAssign}
            onPromote={onTaskPromote}
            onDiscard={onTaskDiscard}
          />
        ) : visible.length === 0 ? (
          <div className="flex h-full items-center justify-center text-center">
            <div className="text-[12.5px] text-dim">
              <div className="mb-1 text-2xl">✓</div>
              {activeCategory === "All"
                ? "You're all caught up. Alerts will appear here as they're generated."
                : `No ${activeCategory.toLowerCase()} alerts.`}
            </div>
          </div>
        ) : (
          visible.map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              onOpenClient={onOpenClient}
              onDismiss={onDismiss}
            />
          ))
        )}
      </div>
    </aside>
  );
}

interface AlertCardProps {
  alert: AlertWithClient;
  onOpenClient: (clientId: string) => void;
  onDismiss: (id: string) => void;
}

function AlertCard({ alert, onOpenClient, onDismiss }: AlertCardProps) {
  const chipClass = SEVERITY_CHIP[alert.severity] ?? SEVERITY_CHIP.FYI;
  const primaryLabel = ACTION_LABEL[alert.action_type] ?? "Act";
  // Show the alert's specific trigger (the promise text, headline, drift figure…),
  // not the generic `why` rationale — otherwise distinct alerts of the same class
  // render identically and look like duplicates. `why` is the secondary context.
  const body = alert.trigger ?? alert.why ?? alert.suggested_action ?? "";
  const subtext = alert.why && alert.why !== body ? alert.why : null;

  return (
    <div className="space-y-2 rounded-xl border border-border bg-panel p-3">
      <div className="flex items-start gap-2">
        <span
          className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${chipClass}`}
        >
          {alert.severity}
        </span>
        <button
          type="button"
          onClick={() => onOpenClient(alert.client_id)}
          className="flex-1 truncate pt-0.5 text-left text-[12px] font-medium text-text leading-tight hover:text-blue transition-colors"
        >
          {alert.client_name}
        </button>
        <span className="shrink-0 pt-0.5 text-[10px] text-dim">
          {alertAge(alert.created_at)}
        </span>
        <button
          type="button"
          onClick={() => onDismiss(alert.id)}
          className="shrink-0 pt-0.5 text-[14px] text-dim transition-colors hover:text-text"
          aria-label="Dismiss"
        >
          ×
        </button>
      </div>

      {body && (
        <p className="line-clamp-2 text-[11.5px] leading-relaxed text-text">
          {body}
        </p>
      )}

      {subtext && (
        <p className="line-clamp-1 text-[10.5px] leading-relaxed text-dim">
          {subtext}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onOpenClient(alert.client_id)}
          className="rounded-lg bg-blue/15 px-2.5 py-1 text-[11px] font-medium text-blue transition-colors hover:bg-blue/25"
        >
          {primaryLabel}
        </button>
        <button
          type="button"
          className="rounded-lg border border-border px-2.5 py-1 text-[11px] text-muted transition-colors hover:text-text"
        >
          Snooze
        </button>
      </div>
    </div>
  );
}
