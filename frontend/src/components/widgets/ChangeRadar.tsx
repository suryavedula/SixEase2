import { useEffect, useState } from "react";
import { chfCompact } from "../../lib/format";
import {
  ChevronDown,
  ChevronRight,
  Mail,
  Newspaper,
  Building2,
  ArrowLeftRight,
  ListChecks,
  Zap,
  Star,
  Plus,
  X,
} from "lucide-react";
import {
  getRadar,
  type RadarEvent,
  type ImpactedClient,
  type RadarResponse,
} from "../../api/radar";
import {
  getFollows,
  addFollow,
  removeFollow,
  type Follow,
} from "../../api/follows";
import { convertAlertToTask } from "../../api/alerts";
import { useCanvasActions } from "../shell/CanvasActions";
import { useRadarLive } from "../shell/RadarLive";
import { WidgetContainer } from "./WidgetContainer";

// Book-wide Change Radar (TASK-061): the top changes across the whole book ranked
// by aggregate impact, each expandable to the clients it hits. Pure consumer of
// GET /radar — every figure comes from the payload, none is computed here (G2).
//
// Three tabs split the same ranked feed for a clear view:
//   • My Topics — changes matching the RM's curated follow list (GET/POST /follows)
//   • News      — externally-sourced changes (source === "news")
//   • Internal  — bank-side signals (CIO / drift / DNA / email)
// "My Topics" is RM-curated: star a change to follow it, or add a free-text topic.

interface ChangeRadarProps {
  limit?: number;
}

type Tab = "topics" | "news" | "internal";

// Fetch a deeper slice than the default top-N so each tab has real content to show;
// the server still ranks the full distribution and returns the top of it.
const FETCH_LIMIT = 40;

const TABS: { key: Tab; label: string; Icon: typeof Star }[] = [
  { key: "topics", label: "My Topics", Icon: Star },
  { key: "news", label: "News", Icon: Newspaper },
  { key: "internal", label: "Internal", Icon: Building2 },
];

type Status =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; data: RadarResponse };

// Per-event batch outcome (created / skipped-no-alert / failed).
interface BatchResult {
  created: number;
  skipped: number;
  failed: number;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60_000));
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days}d ago`;
}

// Ticket badges: news / internal / email. `source` is one of news|cio|drift|dna|email.
function badgeFor(source: string | null): { label: string; Icon: typeof Mail; cls: string } {
  switch (source) {
    case "news":
      return { label: "News", Icon: Newspaper, cls: "border-amber/40 text-amber" };
    case "email":
      return { label: "Email", Icon: Mail, cls: "border-blue/40 text-blue" };
    default: // cio | drift | dna → internal signals
      return { label: "Internal", Icon: Building2, cls: "border-border text-muted" };
  }
}

// Does an event match any RM follow? entity_key exact wins; else keyword substring
// over the human label / canonical key. Mirrors the backend's documented contract.
function matchesFollow(ev: RadarEvent, follows: Follow[]): boolean {
  if (follows.length === 0) return false;
  const hay = `${ev.entity_label ?? ""} ${ev.entity_key ?? ""}`.toLowerCase();
  return follows.some(
    (f) =>
      (!!f.entity_key && !!ev.entity_key && f.entity_key === ev.entity_key) ||
      (!!f.keyword && hay.includes(f.keyword)),
  );
}

// The specific follow backing an event (for the star toggle): prefer entity_key.
function followForEvent(ev: RadarEvent, follows: Follow[]): Follow | undefined {
  const label = (ev.entity_label ?? "").toLowerCase();
  return (
    follows.find((f) => !!f.entity_key && !!ev.entity_key && f.entity_key === ev.entity_key) ??
    follows.find((f) => !!f.keyword && label.includes(f.keyword))
  );
}

export function ChangeRadar({ limit = 10 }: ChangeRadarProps) {
  const { addSpecs } = useCanvasActions();
  const radarPing = useRadarLive(); // bumps when the dispatch loop pushes a change
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [activeTab, setActiveTab] = useState<Tab>("topics");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null); // batch awaiting confirm
  const [busyId, setBusyId] = useState<string | null>(null); // batch running
  const [batchResult, setBatchResult] = useState<Record<string, BatchResult>>({});
  const [taskDone, setTaskDone] = useState<Record<string, boolean>>({}); // `${eventId}:${clientId}`
  // My Topics state
  const [follows, setFollows] = useState<Follow[]>([]);
  const [newTopic, setNewTopic] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  useEffect(() => {
    // Keep the current list visible during a live (radarPing) refresh — only show
    // the skeleton on the very first load, so pushes don't flash the widget.
    setStatus((prev) => (prev.kind === "ok" ? prev : { kind: "loading" }));
    const ctrl = new AbortController();
    // Fetch a deeper slice so the tabs split a meaningful set, not just the top 10.
    getRadar(Math.max(limit, FETCH_LIMIT), ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setStatus({ kind: "ok", data });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setStatus({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, [limit, radarPing]);

  useEffect(() => {
    const ctrl = new AbortController();
    getFollows(ctrl.signal)
      .then((r) => {
        if (!ctrl.signal.aborted) setFollows(r.follows);
      })
      .catch(() => {
        /* a follows read failure shouldn't blank the radar; tabs still work */
      });
    return () => ctrl.abort();
  }, []);

  // Smart initial landing: open on a populated tab the first time so a fresh RM
  // (no follows yet → empty "My Topics") doesn't see "0" when changes exist one
  // tab over. Runs once; manual tab clicks afterwards are never overridden.
  const [autoPicked, setAutoPicked] = useState(false);
  useEffect(() => {
    if (autoPicked || status.kind !== "ok") return;
    const evs = status.data.events;
    const topics = evs.filter((e) => matchesFollow(e, follows)).length;
    if (topics === 0) {
      const news = evs.filter((e) => e.source === "news").length;
      const internal = evs.filter((e) => e.source !== "news").length;
      if (news + internal > 0) setActiveTab(news > internal ? "news" : "internal");
    }
    setAutoPicked(true);
  }, [autoPicked, status, follows]);

  async function reloadFollows() {
    try {
      const r = await getFollows();
      setFollows(r.follows);
    } catch {
      /* keep the last-known list on a transient read failure */
    }
  }

  async function toggleFollow(ev: RadarEvent) {
    setTogglingId(ev.id);
    try {
      const existing = followForEvent(ev, follows);
      if (existing) {
        await removeFollow(existing.id);
      } else {
        await addFollow({
          label: ev.entity_label || ev.action || "Topic",
          entity_key: ev.entity_key,
          entity_type: ev.entity_type,
        });
      }
      await reloadFollows();
    } catch {
      /* leave the control enabled to retry */
    } finally {
      setTogglingId(null);
    }
  }

  async function onAddTopic() {
    const label = newTopic.trim();
    if (!label) return;
    setAddBusy(true);
    try {
      await addFollow({ label });
      setNewTopic("");
      await reloadFollows();
    } catch {
      /* keep the text so the RM can retry */
    } finally {
      setAddBusy(false);
    }
  }

  async function deleteTopic(id: string) {
    try {
      await removeFollow(id);
      await reloadFollows();
    } catch {
      /* no-op; chip stays for retry */
    }
  }

  async function runBatch(ev: RadarEvent) {
    setConfirmId(null);
    setBusyId(ev.id);
    const targets = ev.impacted_clients.filter((c) => c.alert_id);
    const skipped = ev.impacted_clients.length - targets.length;
    const settled = await Promise.allSettled(
      targets.map((c) => convertAlertToTask(c.client_id, c.alert_id as string)),
    );
    const created = settled.filter((s) => s.status === "fulfilled").length;
    const failed = settled.filter((s) => s.status === "rejected").length;
    setBatchResult((m) => ({ ...m, [ev.id]: { created, skipped, failed } }));
    setBusyId(null);
  }

  async function makeTask(eventId: string, c: ImpactedClient) {
    if (!c.alert_id) return;
    const key = `${eventId}:${c.client_id}`;
    try {
      await convertAlertToTask(c.client_id, c.alert_id);
      setTaskDone((m) => ({ ...m, [key]: true }));
    } catch {
      // Surface nothing destructive; leave the button enabled to retry.
    }
  }

  if (status.kind === "loading") {
    return (
      <WidgetContainer title="Change Radar" source="Impact Engine">
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-14 animate-pulse rounded bg-panel2" />
          ))}
        </div>
      </WidgetContainer>
    );
  }

  if (status.kind === "error") {
    return (
      <WidgetContainer title="Change Radar" source="Impact Engine">
        <p className="text-[13px] text-muted">Could not load the change radar.</p>
        <p className="mt-1 text-[11px] text-dim">{status.message}</p>
      </WidgetContainer>
    );
  }

  const { events, unresolved } = status.data;
  const maxImpact = events.reduce((m, e) => Math.max(m, e.impact_score ?? 0), 0);

  // Split the same ranked feed across the three tabs.
  const newsEvents = events.filter((e) => e.source === "news");
  const internalEvents = events.filter((e) => e.source !== "news");
  const topicEvents = events.filter((e) => matchesFollow(e, follows));
  const tabEvents =
    activeTab === "news" ? newsEvents : activeTab === "internal" ? internalEvents : topicEvents;

  function renderEvent(ev: RadarEvent) {
    const open = expandedId === ev.id;
    const badge = badgeFor(ev.source);
    const Icon = badge.Icon;
    const barPct = maxImpact > 0 ? Math.round(((ev.impact_score ?? 0) / maxImpact) * 100) : 0;
    const res = batchResult[ev.id];
    const followed = !!followForEvent(ev, follows);
    return (
      <li key={ev.id} className="rounded-lg border border-border bg-panel/40">
        {/* Header row — expand button + follow star (siblings; buttons can't nest) */}
        <div className="flex items-start">
          <button
            type="button"
            onClick={() => setExpandedId(open ? null : ev.id)}
            className="flex min-w-0 flex-1 items-start gap-3 px-3 py-2.5 text-left"
            aria-expanded={open}
          >
            <span className="mt-0.5 text-dim">
              {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${badge.cls}`}
                >
                  <Icon className="h-3 w-3" />
                  {badge.label}
                </span>
                <span className="truncate text-[13px] font-medium text-text">
                  {ev.entity_label || ev.action || "Change"}
                </span>
                <span className="ml-auto whitespace-nowrap text-[11px] text-dim">
                  {timeAgo(ev.event_ts)}
                </span>
              </span>
              {/* Grounded "why it matters" */}
              <span className="mt-1 block text-[11px] text-muted">
                {ev.action ? `${ev.action} · ` : ""}
                Hits {ev.client_count} client{ev.client_count === 1 ? "" : "s"} · CHF{" "}
                {chfCompact(ev.total_exposure_chf)} exposed
              </span>
              {/* Impact bar (relative to the top event) */}
              <span className="mt-1.5 flex items-center gap-2">
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-panel2">
                  <span
                    className="block h-full rounded-full bg-blue"
                    style={{ width: `${barPct}%` }}
                  />
                </span>
                <span className="w-8 text-right text-[10px] text-dim">{barPct}%</span>
              </span>
            </span>
          </button>
          <button
            type="button"
            onClick={() => toggleFollow(ev)}
            disabled={togglingId === ev.id}
            aria-pressed={followed}
            title={followed ? "Following — click to unfollow" : "Follow this topic"}
            className={`mr-2 mt-2.5 shrink-0 rounded p-1 transition-colors disabled:opacity-40 ${
              followed ? "text-amber" : "text-dim hover:text-text"
            }`}
          >
            <Star className={`h-4 w-4 ${followed ? "fill-current" : ""}`} />
          </button>
        </div>

        {/* Expanded: news content + impacted-client list + batch action */}
        {open && (
          <div className="border-t border-border px-3 py-2">
            {/* News article block — shown only for news events */}
            {ev.source === "news" && ev.entity_label && (
              <div className="mb-2 rounded-md bg-amber/5 border border-amber/20 px-3 py-2">
                <p className="text-[12px] font-medium text-text leading-snug">{ev.entity_label}</p>
                {ev.news_url && !ev.news_url.includes("seeded.internal") ? (
                  <a
                    href={ev.news_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-[11px] text-amber hover:underline"
                  >
                    <Newspaper className="h-3 w-3" />
                    Read article
                  </a>
                ) : (
                  <span className="mt-1 inline-flex items-center gap-1 text-[11px] text-dim">
                    <Newspaper className="h-3 w-3" />
                    Demo article
                  </span>
                )}
              </div>
            )}
            <ul className="divide-y divide-border">
              {ev.impacted_clients.map((c) => {
                const key = `${ev.id}:${c.client_id}`;
                return (
                  <li key={c.client_id} className="py-2">
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-[12px] font-medium text-text">
                            {c.client_name}
                          </span>
                          <span className="whitespace-nowrap text-[11px] text-muted">
                            CHF {chfCompact(c.exposure_chf)}
                            {c.exposure_pct != null ? ` · ${c.exposure_pct.toFixed(1)}%` : ""}
                          </span>
                          {c.drift_caused != null && (
                            <span className="whitespace-nowrap text-[11px] text-red">
                              {c.drift_caused > 0 ? "+" : ""}
                              {c.drift_caused.toFixed(1)}pp drift
                            </span>
                          )}
                        </div>
                        {c.dna_note && <p className="mt-0.5 text-[11px] text-dim">{c.dna_note}</p>}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <ActionBtn
                          label="Swap"
                          Icon={ArrowLeftRight}
                          onClick={() =>
                            addSpecs([
                              { component: "PortfolioView", props: { clientId: c.client_id } },
                            ])
                          }
                        />
                        <ActionBtn
                          label={taskDone[key] ? "Task ✓" : "Task"}
                          Icon={ListChecks}
                          disabled={!c.alert_id || taskDone[key]}
                          title={c.alert_id ? undefined : "No alert to convert"}
                          onClick={() => makeTask(ev.id, c)}
                        />
                        <ActionBtn
                          label="Email"
                          Icon={Mail}
                          onClick={() =>
                            addSpecs([
                              { component: "EmailDraft", props: { clientId: c.client_id } },
                            ])
                          }
                        />
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>

            {/* Batch: one review task per impacted client (human-in-the-loop) */}
            <div className="mt-2 flex items-center gap-2 border-t border-border pt-2">
              <Zap className="h-3.5 w-3.5 text-blue" />
              {res ? (
                <span className="text-[11px] text-muted">
                  Created {res.created} review task{res.created === 1 ? "" : "s"}
                  {res.skipped ? ` · ${res.skipped} skipped (no alert)` : ""}
                  {res.failed ? ` · ${res.failed} failed` : ""}
                </span>
              ) : confirmId === ev.id ? (
                <>
                  <span className="text-[11px] text-muted">
                    Create {ev.impacted_clients.filter((c) => c.alert_id).length} review tasks?
                  </span>
                  <button
                    type="button"
                    onClick={() => runBatch(ev)}
                    disabled={busyId === ev.id}
                    className="rounded bg-blue/15 px-2 py-1 text-[11px] font-medium text-blue hover:bg-blue/25 disabled:opacity-50"
                  >
                    {busyId === ev.id ? "Creating…" : "Confirm"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmId(null)}
                    className="rounded px-2 py-1 text-[11px] text-dim hover:text-text"
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmId(ev.id)}
                  className="rounded bg-panel2 px-2 py-1 text-[11px] font-medium text-muted hover:bg-panel3 hover:text-text"
                >
                  {ev.suggested_batch_action ||
                    `Batch: create review tasks for all ${ev.client_count}`}
                </button>
              )}
            </div>
          </div>
        )}
      </li>
    );
  }

  // Per-tab empty copy.
  const emptyCopy: Record<Tab, string> = {
    topics:
      follows.length === 0
        ? "You're not following any topics yet. Star a change in News or Internal — or add one above — to track it here."
        : "None of your followed topics changed right now — you're caught up.",
    news: "No news-driven changes across the book right now.",
    internal: "No internal (CIO / drift / DNA) changes right now.",
  };

  return (
    <WidgetContainer
      title="Change Radar"
      source="Impact Engine"
      badges={
        <span className="rounded-full bg-panel3 px-2 py-0.5 text-[10px] font-medium text-muted">
          {events.length} change{events.length === 1 ? "" : "s"}
        </span>
      }
    >
      {events.length === 0 && unresolved.length === 0 ? (
        <p className="text-[13px] text-muted">
          Nothing changed across the book — you're all caught up.
        </p>
      ) : (
        <>
          {/* Tabs */}
          <div className="mb-3 flex items-center gap-1 rounded-lg bg-panel2 p-0.5">
            {TABS.map((t) => {
              const active = activeTab === t.key;
              const count =
                t.key === "news"
                  ? newsEvents.length
                  : t.key === "internal"
                    ? internalEvents.length
                    : topicEvents.length;
              const TabIcon = t.Icon;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setActiveTab(t.key)}
                  className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] font-medium transition-colors ${
                    active ? "bg-panel text-text shadow-sm" : "text-muted hover:text-text"
                  }`}
                >
                  <TabIcon className="h-3.5 w-3.5" />
                  {t.label}
                  <span
                    className={`rounded-full px-1.5 text-[10px] ${
                      active ? "bg-blue/15 text-blue" : "bg-panel3 text-dim"
                    }`}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* My Topics: curate the follow list inline */}
          {activeTab === "topics" && (
            <div className="mb-3 rounded-lg border border-border bg-panel/40 p-2.5">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void onAddTopic();
                }}
                className="flex items-center gap-2"
              >
                <input
                  value={newTopic}
                  onChange={(e) => setNewTopic(e.target.value)}
                  placeholder="Follow a topic — e.g. Nestlé, interest rates, ESG…"
                  className="min-w-0 flex-1 rounded bg-panel2 px-2 py-1 text-[12px] text-text outline-none placeholder:text-dim focus:ring-1 focus:ring-blue/40"
                />
                <button
                  type="submit"
                  disabled={!newTopic.trim() || addBusy}
                  className="inline-flex items-center gap-1 rounded bg-blue/15 px-2 py-1 text-[11px] font-medium text-blue hover:bg-blue/25 disabled:opacity-50"
                >
                  <Plus className="h-3 w-3" />
                  {addBusy ? "Adding…" : "Add"}
                </button>
              </form>
              {follows.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {follows.map((f) => (
                    <span
                      key={f.id}
                      className="inline-flex items-center gap-1 rounded-full border border-amber/30 bg-amber/5 px-2 py-0.5 text-[11px] text-amber"
                    >
                      <Star className="h-3 w-3 fill-current" />
                      {f.label}
                      <button
                        type="button"
                        onClick={() => deleteTopic(f.id)}
                        title="Unfollow"
                        className="ml-0.5 text-amber/70 hover:text-amber"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Tab body */}
          {tabEvents.length === 0 ? (
            <p className="text-[13px] text-muted">{emptyCopy[activeTab]}</p>
          ) : (
            <ul className="space-y-2">{tabEvents.map(renderEvent)}</ul>
          )}
        </>
      )}

      {/* No-fallbacks: surface changes we couldn't resolve to real exposure. */}
      {unresolved.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="mb-1.5 text-[11px] font-medium text-dim">
            Needs attention · couldn't resolve exposure ({unresolved.length})
          </p>
          <ul className="space-y-1">
            {unresolved.map((ev) => (
              <li key={ev.id} className="text-[11px] text-muted">
                <span className="text-text">{ev.entity_label || ev.action || "Change"}</span>
                {ev.unresolved_reason ? ` — ${ev.unresolved_reason}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </WidgetContainer>
  );
}

function ActionBtn({
  label,
  Icon,
  onClick,
  disabled,
  title,
}: {
  label: string;
  Icon: typeof Mail;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="inline-flex items-center gap-1 rounded bg-panel2 px-1.5 py-1 text-[11px] text-muted transition-colors hover:bg-panel3 hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
  );
}
