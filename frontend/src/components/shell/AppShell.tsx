import { useCallback, useEffect, useState } from "react";
import { Header } from "./Header";
import { Canvas } from "./Canvas";
import { ActionCenter } from "./ActionCenter";
import { InputDock } from "./InputDock";
import { CanvasActionsProvider } from "./CanvasActions";
import { RadarLiveContext } from "./RadarLive";
import { useToast } from "../../context/ToastProvider";
import { getBook } from "../../api/book";
import { openRadarStream, type RadarStreamEvent } from "../../api/radar";
import {
  getClientAlerts,
  patchAlertStatus,
  type AlertWithClient,
} from "../../api/alerts";
import { getClientTasks, patchTaskStatus, extractBrief, type TaskWithClient } from "../../api/tasks";
import type { CanvasTileSpec, WidgetSpec } from "../../registry/types";
import { resolveSize } from "../../registry/tileLayout";
import { usePrefs, type DefaultView } from "../../prefs/PrefsProvider";

// Session-stable tile ids. Specs aren't persisted, so a monotonic counter is
// sufficient — pin/close/collapse key off identity rather than array index.
let tileSeq = 0;
const stampTiles = (specs: WidgetSpec[]): CanvasTileSpec[] =>
  specs.map((s) => ({
    ...s,
    id: `tile-${tileSeq++}`,
    size: resolveSize(s),
    collapsed: false,
  }));

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
  holdings: (id) => [{ component: "Client360", props: { clientId: id } }],
  dna: (id) => [{ component: "DnaCard", props: { clientId: id } }],
  portfolio: (id) => [{ component: "PortfolioView", props: { clientId: id } }],
  alerts: (id) => [{ component: "ConflictsList", props: { clientId: id } }],
};

export function AppShell() {
  const { prefs, setPref } = usePrefs();
  const { actionCenterOpen } = prefs;
  const { toast } = useToast();
  const [alerts, setAlerts] = useState<AlertWithClient[]>([]);
  const [tasks, setTasks] = useState<TaskWithClient[]>([]);
  const [clients, setClients] = useState<BookClient[]>([]);
  // On open, the first thing the RM sees is the book-wide Change Radar ("what
  // happened"): it fetches GET /radar on mount and, when nothing has changed,
  // shows its own "nothing changed" message. Clearing the canvas drops back to
  // the conversational empty state.
  const [specs, setSpecs] = useState<CanvasTileSpec[]>(() =>
    stampTiles([{ component: "ChangeRadar", props: {} }]),
  );
  // Proactive radar push (EPIC-08): a pulse counter bumped on each SSE event so
  // ChangeRadar refetches live, plus a transient toast naming the latest change.
  const [radarPing, setRadarPing] = useState(0);

  // Open the radar SSE stream once on mount; the browser auto-reconnects on drops.
  // A pushed change bumps the pulse (ChangeRadar refetches) and raises a toast.
  useEffect(() => {
    const es = openRadarStream((ev: RadarStreamEvent) => {
      setRadarPing((p) => p + 1);
      toast({
        message: `New change · ${ev.entity_label || ev.action || "update"}`,
        durationMs: 6000,
      });
    });
    return () => es.close();
  }, [toast]);

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

  // Re-fetch tasks for all clients — used by the poll below so autonomously
  // executed Auto tasks surface their result (running → done) without a reload.
  const refreshTasks = useCallback(async () => {
    if (!clients.length) return;
    const results = await Promise.allSettled(
      clients.map((c) => getClientTasks(c.client_id)),
    );
    const all: TaskWithClient[] = [];
    results.forEach((r) => {
      if (r.status === "fulfilled") {
        const { client_id, client_name, tasks: clientTasks } = r.value;
        clientTasks.forEach((t) => all.push({ ...t, client_id, client_name }));
      }
    });
    setTasks(all);
  }, [clients]);

  // The task runner executes Auto tasks in the background; poll so the brief
  // appears in the Action Center shortly after it completes.
  useEffect(() => {
    const id = setInterval(refreshTasks, 8000);
    return () => clearInterval(id);
  }, [refreshTasks]);

  const alertCount = alerts.length;

  // Re-insert an alert into the open list if it isn't already there (revert/undo).
  const restoreAlerts = useCallback((toRestore: AlertWithClient[]) => {
    setAlerts((prev) => {
      const have = new Set(prev.map((a) => a.id));
      const fresh = toRestore.filter((a) => !have.has(a.id));
      return fresh.length ? [...prev, ...fresh] : prev;
    });
  }, []);

  // Undo: reopen alerts on the backend (status → open) and restore them locally.
  const reopenAlerts = useCallback(
    (toReopen: AlertWithClient[]) => {
      restoreAlerts(toReopen);
      toReopen.forEach((a) =>
        patchAlertStatus(a.client_id, a.id, { status: "open" }).catch(() => {}),
      );
    },
    [restoreAlerts],
  );

  // Dismiss: persist (status → dismissed) so it stays gone across reloads.
  // Optimistic removal; on failure the alert is restored.
  async function handleDismiss(alert: AlertWithClient) {
    setAlerts((prev) => prev.filter((a) => a.id !== alert.id));
    try {
      await patchAlertStatus(alert.client_id, alert.id, { status: "dismissed" });
      toast({
        message: "Alert dismissed",
        action: { label: "Undo", onClick: () => reopenAlerts([alert]) },
      });
    } catch {
      restoreAlerts([alert]);
      toast({ message: "Couldn't dismiss — try again" });
    }
  }

  // Snooze for N days: persist the transition, then drop it from the open list.
  // On failure it stays put rather than silently vanishing.
  async function handleSnooze(alert: AlertWithClient, days: number) {
    const until = new Date(Date.now() + days * 24 * 60 * 60 * 1000);
    try {
      await patchAlertStatus(alert.client_id, alert.id, {
        status: "snoozed",
        snoozed_until: until.toISOString(),
      });
      setAlerts((prev) => prev.filter((a) => a.id !== alert.id));
      toast({
        message: `Snoozed until ${until.toLocaleDateString()}`,
        action: { label: "Undo", onClick: () => reopenAlerts([alert]) },
      });
    } catch {
      toast({ message: "Couldn't snooze — try again" });
    }
  }

  // Mark all read: persist each as dismissed (no bulk endpoint yet). Optimistic
  // clear; any that fail are restored. Undo reopens the ones that were cleared.
  async function handleMarkAllRead() {
    const snapshot = alerts;
    if (snapshot.length === 0) return;
    setAlerts([]);
    const results = await Promise.allSettled(
      snapshot.map((a) =>
        patchAlertStatus(a.client_id, a.id, { status: "dismissed" }),
      ),
    );
    const failed = snapshot.filter((_, i) => results[i].status === "rejected");
    const cleared = snapshot.filter((_, i) => results[i].status === "fulfilled");
    if (failed.length) restoreAlerts(failed);
    toast({
      message: `${cleared.length} alert${cleared.length === 1 ? "" : "s"} cleared`,
      action: { label: "Undo", onClick: () => reopenAlerts(cleared) },
    });
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

  const handleAddSpecs = useCallback((newSpecs: WidgetSpec[]) => {
    setSpecs((prev) => [...prev, ...stampTiles(newSpecs)]);
  }, []);

  function handleTaskPromote(task: TaskWithClient) {
    // Open the full brief on the canvas. Does NOT close the task — the RM reads it
    // and decides; "Discard" dismisses it explicitly. extractBrief handles both the
    // normalized and older nested result shapes.
    const brief = extractBrief(task.result);
    handleAddSpecs([
      {
        component: "Research",
        props: {
          clientId: task.client_id,
          taskTitle: task.title,
          summary: brief.summary ?? undefined,
          citations: brief.citations,
          recommendations: brief.recommendations,
          provenance: brief.provenance,
        },
      },
    ]);
  }

  const handleClearSpecs = useCallback(() => {
    setSpecs([]);
  }, []);

  function handleOpenClient(id: string) {
    handleAddSpecs(DEFAULT_VIEW_SPECS[prefs.defaultView](id));
  }

  // An alert's primary action opens the working view that action implies, not the
  // generic client profile. Rebalance (Trade) → the before/after CIO-swap screen;
  // Draft Message (ReachOut) → the email composer; everything else falls back to
  // the client's default view.
  function handleAlertAction(alert: AlertWithClient) {
    if (alert.action_type === "Trade") {
      handleAddSpecs([
        { component: "BeforeAfter", props: { clientId: alert.client_id } },
      ]);
    } else if (alert.action_type === "ReachOut") {
      handleAddSpecs([
        {
          component: "EmailDraft",
          props: { clientId: alert.client_id, alertId: alert.id },
        },
      ]);
    } else {
      handleOpenClient(alert.client_id);
    }
  }

  // Per-tile chrome (TASK-069). collapse/pin mutate flags; close removes the tile.
  const handleToggleCollapse = useCallback((id: string) => {
    setSpecs((prev) =>
      prev.map((t) => (t.id === id ? { ...t, collapsed: !t.collapsed } : t)),
    );
  }, []);

  const handleSetRail = useCallback(
    (id: string, rail: "left" | null) => {
      setSpecs((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, rail: rail ?? undefined } : t,
        ),
      );
    },
    [],
  );

  const handleCloseTile = useCallback((id: string) => {
    setSpecs((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Derive lastClientId from the most recent spec that carried one
  const lastClientId =
    [...specs].reverse().find((s) => typeof s.props.clientId === "string")
      ?.props.clientId as string | undefined;
  const leftPinned = specs.filter((t) => t.rail === "left");

  // Two-column desktop grid: Action Center rail on the left, canvas on the right.
  // The rail collapses to a thin 48px strip (its own re-expand affordance) rather
  // than vanishing. Static class strings so Tailwind's JIT keeps them. The rail is
  // desktop-only (lg+); on mobile the columns collapse and the canvas/rail stack as
  // rows (railRows) — canvas first (1fr), rail below (auto).
  const railCols = actionCenterOpen
    ? "lg:grid-cols-[326px_1fr]"
    : "lg:grid-cols-[48px_1fr]";
  const railRows = actionCenterOpen
    ? "grid-rows-[1fr_auto] lg:grid-rows-1"
    : "grid-rows-1";

  return (
    <RadarLiveContext.Provider value={radarPing}>
    <CanvasActionsProvider addSpecs={handleAddSpecs} openClient={handleOpenClient} refreshTasks={refreshTasks}>
    <div data-density={prefs.density} className="grid h-screen grid-rows-[auto_1fr_auto] overflow-hidden">
      <Header />

      {/* Canvas is first in the DOM so it stacks on top on mobile; on desktop the
          Action Center's `lg:order-first` pulls it into the left column. */}
      <div className={`grid min-h-0 ${railRows} ${railCols}`}>
        <Canvas
          specs={specs}
          onClearSpecs={handleClearSpecs}
          onToggleCollapse={handleToggleCollapse}
          onSetRail={handleSetRail}
          onCloseTile={handleCloseTile}
        />
        <ActionCenter
          open={actionCenterOpen}
          alerts={alerts}
          tasks={tasks}
          alertCount={alertCount}
          pinnedTiles={leftPinned}
          onOpen={() => setPref("actionCenterOpen", true)}
          onClose={() => setPref("actionCenterOpen", false)}
          onUnpin={(id) => handleSetRail(id, null)}
          onOpenClient={handleOpenClient}
          onAlertAction={handleAlertAction}
          onDismiss={handleDismiss}
          onSnooze={handleSnooze}
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
    </CanvasActionsProvider>
    </RadarLiveContext.Provider>
  );
}
