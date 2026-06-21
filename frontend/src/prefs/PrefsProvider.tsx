import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type DefaultView = "holdings" | "dna" | "portfolio" | "alerts";
export type WidgetDensity = "dense" | "narrative";

export interface Prefs {
  defaultView: DefaultView;
  density: WidgetDensity;
  // Action Center rail open/closed (TASK-070). Persisted so it survives reload.
  actionCenterOpen: boolean;
}

const DEFAULT_PREFS: Prefs = {
  defaultView: "holdings",
  density: "narrative",
  actionCenterOpen: true,
};
const STORAGE_KEY = "waw-prefs";

function readInitialPrefs(): Prefs {
  if (typeof window === "undefined") return DEFAULT_PREFS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<Prefs>;
    const defaultView =
      parsed.defaultView === "holdings" ||
      parsed.defaultView === "dna" ||
      parsed.defaultView === "portfolio" ||
      parsed.defaultView === "alerts"
        ? parsed.defaultView
        : DEFAULT_PREFS.defaultView;
    const density =
      parsed.density === "dense" || parsed.density === "narrative"
        ? parsed.density
        : DEFAULT_PREFS.density;
    // Older blobs predate this key — fall back to default when absent.
    const actionCenterOpen =
      typeof parsed.actionCenterOpen === "boolean"
        ? parsed.actionCenterOpen
        : DEFAULT_PREFS.actionCenterOpen;
    return { defaultView, density, actionCenterOpen };
  } catch {
    return DEFAULT_PREFS;
  }
}

interface PrefsContextValue {
  prefs: Prefs;
  setPrefs: (prefs: Prefs) => void;
  setPref: <K extends keyof Prefs>(key: K, value: Prefs[K]) => void;
}

const PrefsContext = createContext<PrefsContextValue | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefsState] = useState<Prefs>(readInitialPrefs);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  }, [prefs]);

  const setPrefs = useCallback((next: Prefs) => setPrefsState(next), []);
  const setPref = useCallback(
    <K extends keyof Prefs>(key: K, value: Prefs[K]) =>
      setPrefsState((p) => ({ ...p, [key]: value })),
    [],
  );

  const value = useMemo(
    () => ({ prefs, setPrefs, setPref }),
    [prefs, setPrefs, setPref],
  );

  return <PrefsContext value={value}>{children}</PrefsContext>;
}

export function usePrefs(): PrefsContextValue {
  const ctx = useContext(PrefsContext);
  if (!ctx) throw new Error("usePrefs must be used within a PrefsProvider");
  return ctx;
}
