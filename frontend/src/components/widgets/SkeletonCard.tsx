// Reusable loading skeleton for bare widgets (a titled card with a few shimmer
// rows). Replaces the hand-rolled `animate-pulse` blocks that were copy-pasted
// across the data-fetching widgets. Pair with CanvasTile padding (bare widgets)
// or drop inside a WidgetContainer for self-contained ones.

interface SkeletonCardProps {
  // Number of shimmer rows under the title bar.
  lines?: number;
  // Render the leading wider "title" row. Default true.
  title?: boolean;
  className?: string;
}

export function SkeletonCard({ lines = 3, title = true, className }: SkeletonCardProps) {
  return (
    <div
      className={`rounded-2xl border border-border bg-panel p-4 space-y-3 ${className ?? ""}`}
    >
      {title && <div className="h-5 w-32 animate-pulse rounded bg-panel3" />}
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-4 w-full animate-pulse rounded bg-panel3" />
      ))}
    </div>
  );
}
