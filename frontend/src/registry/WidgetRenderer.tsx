import { registry } from "./registry";
import type { WidgetSpec } from "./types";

interface FallbackCardProps {
  component?: string;
  message?: string;
}

export function FallbackCard({ component, message }: FallbackCardProps) {
  return (
    <div className="rounded-[14px] border border-border bg-panel p-4">
      <p className="text-[13px] font-medium text-muted">
        {component ? `Unknown widget: ${component}` : (message ?? "Widget unavailable")}
      </p>
      {component && message && (
        <p className="mt-1 text-[12px] text-dim">{message}</p>
      )}
    </div>
  );
}

export function WidgetRenderer({ spec }: { spec: WidgetSpec }) {
  if (spec.component === "FallbackCard") {
    return <FallbackCard message={spec.props.message as string | undefined} />;
  }

  const Component = registry.get(spec.component);
  if (!Component) {
    return <FallbackCard component={spec.component} />;
  }

  return <Component {...(spec.props as Record<string, unknown>)} />;
}
