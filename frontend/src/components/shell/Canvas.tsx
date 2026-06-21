// Central conversation canvas (TASK-003, TASK-041, TASK-043, TASK-066, TASK-068).
// Renders the interleaved transcript of chat bubbles and generative-UI widgets as
// a full-width bento grid. The canvas scrolls with the page and auto-scrolls to
// the newest tile as it's appended. Tiles can be collapsed, maximized, closed, or
// pinned to a side rail (the "save this view" affordance).

import { useCallback, useEffect, useRef, useState } from "react";
import { WidgetRenderer } from "../../registry/WidgetRenderer";
import type { CanvasTileSpec } from "../../registry/types";
import { CanvasTile } from "./CanvasTile";
import { usePrefs } from "../../prefs/PrefsProvider";

// Conversational specs render bare (full-width, no chrome) — they keep today's
// chat feel inside the grid rather than becoming collapsible/closable tiles.
const BARE = new Set(["ChatMessage", "SourcesFooter"]);

interface CanvasProps {
  specs: CanvasTileSpec[];
  onClearSpecs: () => void;
  onToggleCollapse: (id: string) => void;
  onSetRail: (id: string, rail: "left" | null) => void;
  onCloseTile: (id: string) => void;
}

export function Canvas({
  specs,
  onClearSpecs,
  onToggleCollapse,
  onSetRail,
  onCloseTile,
}: CanvasProps) {
  // scrollRef owns the scroll; contentRef wraps the grid tiles so a ResizeObserver
  // can watch the *content* height (the scroll viewport's own box never changes).
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const seenIds = useRef<Set<string>>(new Set());
  // Whether to keep the view pinned to the newest tile. True until the RM scrolls
  // up to read something; re-armed whenever a new tile is appended.
  const stickToBottom = useRef(true);
  const [maximizedId, setMaximizedId] = useState<string | null>(null);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());

  const { prefs } = usePrefs();
  // Railed tiles are docked to a sidebar and never rendered in the canvas grid.
  const gridSpecs = specs.filter((t) => !t.rail);

  // Scroll the container directly — scrollIntoView traverses all ancestors and can
  // be intercepted by the overflow-hidden parent, silently doing nothing.
  const scrollToBottom = useCallback((behavior: ScrollBehavior) => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  // The RM scrolling up to read pauses auto-follow; scrolling back near the bottom
  // re-arms it. 64px slop tolerates sub-pixel rounding and momentum overshoot.
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 64;
  }, []);

  // A new tile was appended → re-arm follow and jump to the end. rAF lets the new
  // tile commit to layout before we measure scrollHeight.
  useEffect(() => {
    stickToBottom.current = true;
    const id = requestAnimationFrame(() => scrollToBottom("smooth"));
    return () => cancelAnimationFrame(id);
  }, [specs.length, scrollToBottom]);

  // Widgets that fetch async (Client360, PortfolioView, charts) grow their height
  // after mount, which would leave the newest tile off-screen below the fold. Keep
  // the view pinned to the end while content settles — but only while following, so
  // we never yank the RM away from something they scrolled up to read.
  useEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const ro = new ResizeObserver(() => {
      if (stickToBottom.current) scrollToBottom("auto");
    });
    ro.observe(content);
    return () => ro.disconnect();
  }, [scrollToBottom]);

  // Briefly highlight freshly-inserted tiles (TASK-067) so new output is easy to
  // spot in the bento — it may land anywhere in the grid, not just the bottom.
  // Diff against ids already seen so collapse/pin/close re-renders never re-fire
  // the ring; the ring fades out via each tile's `transition-shadow`.
  useEffect(() => {
    const fresh = specs
      .filter((s) => !seenIds.current.has(s.id))
      .map((s) => s.id);
    specs.forEach((s) => seenIds.current.add(s.id));
    if (fresh.length === 0) return;
    setNewIds(new Set(fresh));
    const t = setTimeout(() => setNewIds(new Set()), 1400);
    return () => clearTimeout(t);
  }, [specs]);

  if (specs.length === 0) {
    return (
      <main className="h-full overflow-auto p-[18px]">
        <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-border bg-panel2 text-2xl">
            ◆
          </div>
          <h1 className="mb-1 text-[22px] font-semibold tracking-tight">
            Ask your workbench
          </h1>
          <p className="max-w-md text-[14px] text-muted">
            Have a conversation — ask about a client, their portfolio, or what
            needs your attention. Answers and live views are generated here as
            you talk.
          </p>
          <p className="mt-3 text-[12px] text-dim">
            Try{" "}
            <code className="font-mono text-muted">
              How does Schneider's portfolio fit her values?
            </code>{" "}
            or <code className="font-mono text-muted">/client Schneider</code>
          </p>

          {/* Quick orientation for first-time RMs — the entry points that aren't
              obvious from a blank canvas. */}
          <div className="mt-6 grid max-w-lg gap-2 text-left text-[12px] text-muted sm:grid-cols-2">
            <div className="rounded-lg border border-border bg-panel2/50 p-3">
              <div className="font-medium text-text">Shortcuts below</div>
              Radar, Clients, Portfolio, Values & Rebalance open a view in one
              click.
            </div>
            <div className="rounded-lg border border-border bg-panel2/50 p-3">
              <div className="font-medium text-text">Type / for commands</div>
              <code className="font-mono">/client</code>,{" "}
              <code className="font-mono">/book</code>,{" "}
              <code className="font-mono">/portfolio</code>,{" "}
              <code className="font-mono">/note</code> — autocomplete as you type.
            </div>
            <div className="rounded-lg border border-border bg-panel2/50 p-3">
              <div className="font-medium text-text">🎙 Dictate a note</div>
              Tap the mic to record; it's transcribed and structured for you to
              review.
            </div>
            <div className="rounded-lg border border-border bg-panel2/50 p-3">
              <div className="font-medium text-text">Pin to keep a view</div>
              Hover a tile and pin it to the left rail to keep it handy.
            </div>
          </div>
        </div>
      </main>
    );
  }

  return (
    // `relative` + non-scrolling main makes this the containing block for the
    // maximize overlay, so a maximized tile fills the canvas area only — it never
    // overlaps the header or input dock. An inner div owns the scroll. `@container`
    // makes the bento grid size to the *canvas* width (not the viewport), so its
    // column count stays correct as the side rails open and close (TASK-067).
    <main className="@container relative flex h-full flex-col overflow-hidden p-[18px]">
      {/* Canvas toolbar — centred on the same column as the grid so the clear
          button lines up with the bento's right edge. */}
      <div className="mx-auto mb-3 flex w-full max-w-[1600px] shrink-0 items-center justify-end">
        <button
          type="button"
          onClick={onClearSpecs}
          className="text-[12px] text-muted transition-colors hover:text-text"
        >
          × clear canvas
        </button>
      </div>

      {/* Scroll viewport owns the scrollbar; the inner grid is the observed content.
          Bento grid (TASK-067): a container-query grid at 1 / 2 / 3 columns (≥48rem
          → 2, ≥72rem → 3). The grid is `w-full` up to `max-w-[1600px]` then centred
          (`mx-auto`), so it fills the canvas on normal screens and sits centred with
          even gutters on ultra-wide displays rather than stretching edge-to-edge.
          `items-start` keeps each tile at its natural height; `wide`/`tall` tiles
          span via SPAN_CLASS. The view auto-follows the newest tile as it lands. */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-auto"
      >
        <div
          ref={contentRef}
          className={`mx-auto grid w-full max-w-[1600px] grid-cols-1 content-start items-start @3xl:grid-cols-2 @6xl:grid-cols-3 ${
            prefs.density === "dense" ? "gap-3" : "gap-4"
          }`}
        >
          {gridSpecs.map((tile) =>
            BARE.has(tile.component) ? (
              <div
                key={tile.id}
                className="col-span-full motion-safe:animate-tile-enter"
              >
                <WidgetRenderer spec={tile} />
              </div>
            ) : (
              <CanvasTile
                key={tile.id}
                tile={tile}
                maximized={maximizedId === tile.id}
                isNew={newIds.has(tile.id)}
                onToggleCollapse={onToggleCollapse}
                onToggleMaximize={(id) =>
                  setMaximizedId((cur) => (cur === id ? null : id))
                }
                onSetRail={onSetRail}
                onClose={(id) => {
                  if (maximizedId === id) setMaximizedId(null);
                  onCloseTile(id);
                }}
              >
                <WidgetRenderer spec={tile} />
              </CanvasTile>
            ),
          )}
        </div>
      </div>

      {/* Scrim behind a maximized tile — bounded to the canvas, not the viewport */}
      {maximizedId && (
        <div
          className="absolute inset-0 z-30 bg-black/30"
          onClick={() => setMaximizedId(null)}
          aria-hidden
        />
      )}
    </main>
  );
}
