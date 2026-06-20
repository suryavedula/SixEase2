import { useState } from "react";
import type { TaskWithClient } from "../../api/tasks";

const MODE_CHIP: Record<string, string> = {
  Auto: "bg-violet/10 text-violet border-violet/30",
  Manual: "bg-panel2 text-muted border-border",
};

const STATUS_CHIP: Record<string, string> = {
  created: "bg-blue/10 text-blue border-blue/30",
  running: "bg-amber/10 text-amber border-amber/30",
  done: "bg-green/10 text-green border-green/30",
  closed: "bg-panel2 text-dim border-border",
};

const SOURCE_LABEL: Record<string, string> = {
  alert: "Alert",
  note: "Note",
  promise: "Promise",
};

function taskAge(iso: string): string {
  const h = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
  if (h < 1) return "<1h";
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

interface TasksListProps {
  tasks: TaskWithClient[];
  onOpenClient: (clientId: string) => void;
  onAssign?: (task: TaskWithClient) => void;
  onPromote?: (task: TaskWithClient) => void;
  onDiscard?: (task: TaskWithClient) => void;
}

export function TasksList({
  tasks,
  onOpenClient,
  onAssign,
  onPromote,
  onDiscard,
}: TasksListProps) {
  if (tasks.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-center">
        <div className="text-[12.5px] text-dim">
          <div className="mb-1 text-2xl">✓</div>
          No tasks yet. Tasks are created from alerts, notes, and promises.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {tasks.map((task) => (
        <TaskCard
          key={task.id}
          task={task}
          onOpenClient={onOpenClient}
          onAssign={onAssign}
          onPromote={onPromote}
          onDiscard={onDiscard}
        />
      ))}
    </div>
  );
}

interface TaskCardProps {
  task: TaskWithClient;
  onOpenClient: (clientId: string) => void;
  onAssign?: (task: TaskWithClient) => void;
  onPromote?: (task: TaskWithClient) => void;
  onDiscard?: (task: TaskWithClient) => void;
}

function TaskCard({
  task,
  onOpenClient,
  onAssign,
  onPromote,
  onDiscard,
}: TaskCardProps) {
  const [resultOpen, setResultOpen] = useState(false);

  const modeChip = MODE_CHIP[task.execution_mode] ?? MODE_CHIP.Manual;
  const statusChip = STATUS_CHIP[task.status] ?? STATUS_CHIP.created;
  const sourceLabel = SOURCE_LABEL[task.source ?? ""] ?? task.source ?? "—";

  const hasResult = task.status === "done" && task.result != null;
  const resultSummary =
    hasResult && typeof task.result?.summary === "string"
      ? task.result.summary
      : hasResult
        ? JSON.stringify(task.result).slice(0, 200)
        : null;

  return (
    <div className="space-y-2 rounded-xl border border-border bg-panel p-3">
      {/* Header row */}
      <div className="flex items-start gap-2">
        <span
          className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${modeChip}`}
        >
          {task.execution_mode}
        </span>
        <button
          type="button"
          onClick={() => onOpenClient(task.client_id)}
          className="flex-1 truncate pt-0.5 text-left text-[12px] font-medium text-text leading-tight hover:text-blue transition-colors"
        >
          {task.client_name}
        </button>
        <span className="shrink-0 pt-0.5 text-[10px] text-dim">
          {taskAge(task.created_at)}
        </span>
      </div>

      {/* Task title */}
      {task.title && (
        <p className="line-clamp-2 text-[11.5px] leading-relaxed text-muted">
          {task.title}
        </p>
      )}

      {/* Status row */}
      <div className="flex items-center gap-2">
        {task.status === "running" ? (
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-amber animate-pulse" />
            <span
              className={`rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${statusChip}`}
            >
              running
            </span>
          </span>
        ) : (
          <span
            className={`rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${statusChip}`}
          >
            {task.status}
          </span>
        )}
        <span className="text-[10px] text-dim">via {sourceLabel}</span>
      </div>

      {/* Collapsible result panel (done tasks with result) */}
      {hasResult && (
        <div className="rounded-lg border border-border bg-panel2/60">
          <button
            type="button"
            onClick={() => setResultOpen((o) => !o)}
            className="flex w-full items-center justify-between px-2.5 py-1.5 text-left"
          >
            <span className="text-[10px] font-semibold text-muted">
              Research brief
            </span>
            <span className="text-[10px] text-dim">
              {resultOpen ? "▲" : "▼"}
            </span>
          </button>
          {resultOpen && (
            <p className="border-t border-border px-2.5 pb-2 pt-1.5 text-[11px] leading-relaxed text-muted">
              {resultSummary}
            </p>
          )}
        </div>
      )}

      {/* Action buttons */}
      <ActionButtons
        task={task}
        onOpenClient={onOpenClient}
        onAssign={onAssign}
        onPromote={onPromote}
        onDiscard={onDiscard}
      />
    </div>
  );
}

interface ActionButtonsProps {
  task: TaskWithClient;
  onOpenClient: (clientId: string) => void;
  onAssign?: (task: TaskWithClient) => void;
  onPromote?: (task: TaskWithClient) => void;
  onDiscard?: (task: TaskWithClient) => void;
}

function ActionButtons({
  task,
  onOpenClient,
  onAssign,
  onPromote,
  onDiscard,
}: ActionButtonsProps) {
  if (task.status === "closed") return null;

  const discard = onDiscard ? (
    <button
      type="button"
      onClick={() => onDiscard(task)}
      className="rounded-lg border border-border px-2.5 py-1 text-[11px] text-muted transition-colors hover:text-text"
    >
      Discard
    </button>
  ) : null;

  if (task.status === "created" && task.execution_mode === "Manual") {
    return (
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onAssign?.(task)}
          className="rounded-lg bg-blue/15 px-2.5 py-1 text-[11px] font-medium text-blue transition-colors hover:bg-blue/25"
        >
          Assign
        </button>
        {discard}
      </div>
    );
  }

  if (task.status === "created" && task.execution_mode === "Auto") {
    return <div className="flex gap-2">{discard}</div>;
  }

  if (task.status === "running") {
    return <div className="flex gap-2">{discard}</div>;
  }

  if (task.status === "done" && task.result != null) {
    return (
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onPromote?.(task)}
          className="rounded-lg bg-violet/15 px-2.5 py-1 text-[11px] font-medium text-violet transition-colors hover:bg-violet/25"
        >
          Promote
        </button>
        {discard}
      </div>
    );
  }

  // done + no result
  return (
    <div className="flex gap-2">
      <button
        type="button"
        onClick={() => onOpenClient(task.client_id)}
        className="rounded-lg bg-blue/15 px-2.5 py-1 text-[11px] font-medium text-blue transition-colors hover:bg-blue/25"
      >
        Open
      </button>
      {discard}
    </div>
  );
}
