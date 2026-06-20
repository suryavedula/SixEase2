import { useCallback, useEffect, useState } from "react";
import { Header } from "./Header";
import { Canvas } from "./Canvas";
import { ActionCenter } from "./ActionCenter";
import { InputDock } from "./InputDock";
import { getBook } from "../../api/book";
import { getClientAlerts, type AlertWithClient } from "../../api/alerts";
import { getClientTasks, patchTaskStatus, type TaskWithClient } from "../../api/tasks";
import type { WidgetSpec } from "../../registry/types";
import { usePrefs, type DefaultView } from "../../prefs/PrefsProvider";

// App shell layout (TASK-003, TASK-042). CSS grid: header row · body (canvas +
// Action Center drawer) · dock row.
//
// specs[] is lifted here so Canvas (renders) and InputDock (appends) share it.
// clients[] is extracted from the book fetch so InputDock can resolve /client names.

interface BookClient {
  client_id: string;
  client_name: string;
}

const DEFAULT_VIEW_SPECS: Record<DefaultView, (id: string) => WidgetSpec[]> = {
  holdings: (id) => [
    { component: "DnaCard", props: { clientId: id } },
    { component: "HoldingsTable", props: { clientId: id } },
  ],
  dna: (id) => [{ component: "DnaCard", props: { clientId: id } }],
  portfolio: (id) => [
    { component: "DnaCard", props: { clientId: id } },
    { component: "AllocationDonut", props: { clientId: id } },
  ],
  alerts: (id) => [
    { component: "DnaCard", props: { clientId: id } },
    { component: "ConflictsList", props: { clientId: id } },
  ],
};

export function AppShell() {
  const { prefs } = usePrefs();
  const [actionCenterOpen, setActionCenterOpen] = useState(true);
  const [alerts, setAlerts] = useState<AlertWithClient[]>([]);
  const [tasks, setTasks] = useState<TaskWithClient[]>([]);
  const [clients, setClients] = useState<BookClient[]>([]);
  const [specs, setSpecs] = useState<WidgetSpec[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function loadAlerts() {
      try {
        const book = await getBook();
        if (cancelled) return;

        setClients(
          book.clients.map((c) => ({
            client_id: c.client_id,
            client_name: c.client_name,
          })),
        );

        const [alertResults, taskResults] = await Promise.all([
          Promise.allSettled(
            book.clients.map((c) => getClientAlerts(c.client_id, "open")),
          ),
          Promise.allSettled(
            book.clients.map((c) => getClientTasks(c.client_id)),
          ),
        ]);
        if (cancelled) return;

        const allAlerts: AlertWithClient[] = [];
        alertResults.forEach((r) => {
          if (r.status === "fulfilled") {
            const { client_id, client_name, alerts: clientAlerts } = r.value;
            clientAlerts.forEach((a) =>
              allAlerts.push({ ...a, client_id, client_name }),
            );
          }
        });
        setAlerts(allAlerts);

        const allTasks: TaskWithClient[] = [];
        taskResults.forEach((r) => {
          if (r.status === "fulfilled") {
            const { client_id, client_name, tasks: clientTasks } = r.value;
            clientTasks.forEach((t) =>
              allTasks.push({ ...t, client_id, client_name }),
            );
          }
        });
        setTasks(allTasks);
      } catch {
        // Book or data not seeded yet — keep empty state
      }
    }

    loadAlerts();
    return () => {
      cancelled = true;
    };
  }, []);

  const alertCount = alerts.length;

  function handleDismiss(id: string) {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  }

  function handleMarkAllRead() {
    setAlerts([]);
  }

  async function handleTaskAssign(task: TaskWithClient) {
    try {
      await patchTaskStatus(task.client_id, task.id, { status: "running" });
      setTasks((prev) =>
        prev.map((t) => (t.id === task.id ? { ...t, status: "running" } : t)),
      );
    } catch {
      // leave state unchanged on error
    }
  }

  async function handleTaskDiscard(task: TaskWithClient) {
    try {
      await patchTaskStatus(task.client_id, task.id, { status: "closed" });
      setTasks((prev) => prev.filter((t) => t.id !== task.id));
    } catch {
      // leave state unchanged on error
    }
  }

  async function handleTaskPromote(task: TaskWithClient) {
    try {
      await patchTaskStatus(task.client_id, task.id, { status: "closed" });
      setTasks((prev) => prev.filter((t) => t.id !== task.id));
      const result = (task.result ?? {}) as Record<string, unknown>;
      setSpecs((prev) => [
        ...prev,
        {
          component: "TaskResultCard",
          props: {
            clientId: task.client_id,
            taskTitle: task.title,
            summary: result.summary as string | undefined,
            citations: result.citations as
              | { source: string; text: string }[]
              | undefined,
          },
        },
      ]);
    } catch {
      // leave state unchanged on error
    }
  }

  const handleAddSpecs = useCallback((newSpecs: WidgetSpec[]) => {
    setSpecs((prev) => [...prev, ...newSpecs]);
  }, []);

  const handleClearSpecs = useCallback(() => {
    setSpecs([]);
  }, []);

  function handleOpenClient(id: string) {
    setSpecs((prev) => [...prev, ...DEFAULT_VIEW_SPECS[prefs.defaultView](id)]);
  }

  // Derive lastClientId from the most recent spec that carried one
  const lastClientId =
    [...specs].reverse().find((s) => typeof s.props.clientId === "string")
      ?.props.clientId as string | undefined;

  return (
    <div className="grid h-screen grid-rows-[auto_1fr_auto] overflow-hidden">
      <Header
        alertCount={alertCount}
        onToggleActionCenter={() => setActionCenterOpen((o) => !o)}
      />

      <div
        className={`grid min-h-0 ${
          actionCenterOpen
            ? "grid-rows-[1fr_auto] lg:grid-cols-[1fr_326px] lg:grid-rows-1"
            : "grid-cols-1"
        }`}
      >
        <Canvas specs={specs} onClearSpecs={handleClearSpecs} />
        <ActionCenter
          open={actionCenterOpen}
          alerts={alerts}
          tasks={tasks}
          alertCount={alertCount}
          onOpenClient={handleOpenClient}
          onDismiss={handleDismiss}
          onMarkAllRead={handleMarkAllRead}
          onTaskAssign={handleTaskAssign}
          onTaskPromote={handleTaskPromote}
          onTaskDiscard={handleTaskDiscard}
        />
      </div>

      <InputDock
        clients={clients}
        onAddSpecs={handleAddSpecs}
        lastClientId={lastClientId}
      />
    </div>
  );
}
