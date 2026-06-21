import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

// Reusable toast/confirmation layer (generalises the bespoke radar `liveToast`
// that used to live in AppShell). A toast is a short pill at top-center that
// auto-dismisses; it may carry one action (e.g. "Undo") that the RM can click
// before it fades. Mirrors the PrefsProvider/RadarLive context shape.
//
// Usage:
//   const { toast } = useToast();
//   toast({ message: "Alert dismissed", action: { label: "Undo", onClick } });

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  message: string;
  action?: ToastAction;
  // Time before auto-dismiss. Defaults longer when an action is present so the
  // RM has time to hit Undo.
  durationMs?: number;
}

interface ActiveToast extends ToastOptions {
  id: number;
}

interface ToastContextValue {
  toast: (opts: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ActiveToast[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (opts: ToastOptions) => {
      const id = ++seq.current;
      const duration = opts.durationMs ?? (opts.action ? 6000 : 4000);
      setToasts((prev) => [...prev, { ...opts, id }]);
      window.setTimeout(() => dismiss(id), duration);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext value={value}>
      {children}
      {/* Stack — top-center, above everything. Wrapper ignores pointer events so
          it never blocks the canvas; each pill re-enables them for its Undo. */}
      <div className="pointer-events-none fixed left-1/2 top-3 z-[60] flex -translate-x-1/2 flex-col items-center gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex items-center gap-2 rounded-full border border-blue/40 bg-panel px-3 py-1.5 text-[12px] text-text shadow-lg"
            role="status"
          >
            <span className="h-2 w-2 rounded-full bg-blue" />
            <span>{t.message}</span>
            {t.action && (
              <button
                type="button"
                onClick={() => {
                  t.action!.onClick();
                  dismiss(t.id);
                }}
                className="ml-1 rounded-full px-2 py-0.5 text-[11px] font-semibold text-blue transition-colors hover:bg-blue/10"
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
