import { createContext, useContext, type ReactNode } from "react";
import type { WidgetSpec } from "../../registry/types";

// Bridges the ported workbench components (which used setCanvasState to switch
// full-screen templates) onto our generative-UI model: a button instead appends
// new widgets to the stacked canvas. Provided by AppShell, consumed by widgets.

interface CanvasActions {
  addSpecs: (specs: WidgetSpec[]) => void;
  // Opens a client using the RM's default-view preference (NOT a hardcoded widget),
  // so the "Default view" pref governs every client-open entry point uniformly.
  openClient: (clientId: string) => void;
  // Re-pull the book's tasks into the Action Center (e.g. after a widget creates a
  // task, like a BeforeAfter swap decision) so it surfaces without a manual reload.
  refreshTasks: () => void;
}

const CanvasActionsContext = createContext<CanvasActions>({
  addSpecs: () => {},
  openClient: () => {},
  refreshTasks: () => {},
});

export function CanvasActionsProvider({
  addSpecs,
  openClient,
  refreshTasks,
  children,
}: {
  addSpecs: (specs: WidgetSpec[]) => void;
  openClient: (clientId: string) => void;
  refreshTasks: () => void;
  children: ReactNode;
}) {
  return (
    <CanvasActionsContext.Provider value={{ addSpecs, openClient, refreshTasks }}>
      {children}
    </CanvasActionsContext.Provider>
  );
}

export function useCanvasActions(): CanvasActions {
  return useContext(CanvasActionsContext);
}
