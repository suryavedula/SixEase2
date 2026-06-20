// Bottom input dock (TASK-042, TASK-043, TASK-046). Slash-command / NL / voice entry.
//
// Two paths:
//   • Slash commands (/client, /book, /portfolio, /note) resolve locally and
//     instantly — deterministic view-summons for power users.
//   • Everything else is a real conversation: the query goes to the LLM
//     orchestrator (/orchestrate), which replies and picks generative-UI widgets.
//     User + assistant turns render as chat bubbles in the canvas, interleaved
//     with the widgets, and recent turns are sent back as context.

import { useEffect, useRef, useState } from "react";
import { useVoiceInput } from "../../hooks/useVoiceInput";
import { postOrchestrate, type ChatTurn, type ScopeTab } from "../../api/orchestrate";
import type { WidgetSpec } from "../../registry/types";

const SCOPE_TABS: { key: ScopeTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "clients", label: "Clients" },
  { key: "market", label: "Market" },
  { key: "documents", label: "Documents" },
  { key: "analysis", label: "Analysis" },
];

const QUICK_COMMANDS = [
  "/client Schneider",
  "/book",
  "/portfolio analysis",
  "Analyse this client's values fit",
] as const;

interface Client {
  client_id: string;
  client_name: string;
}

interface InputDockProps {
  clients: Client[];
  onAddSpecs: (specs: WidgetSpec[]) => void;
  lastClientId?: string | null;
}

function fallback(message: string): WidgetSpec[] {
  return [{ component: "FallbackCard", props: { message } }];
}

function findClient(text: string, clients: Client[]): Client | undefined {
  const lower = text.toLowerCase();
  let best: Client | undefined;
  let bestLen = 0;
  for (const c of clients) {
    const name = c.client_name.toLowerCase();
    for (const tok of [name, ...name.split(/\s+/)]) {
      if (tok.length >= 3 && lower.includes(tok) && tok.length > bestLen) {
        best = c;
        bestLen = tok.length;
      }
    }
  }
  return best;
}

// Resolve a slash command locally. Returns null for non-slash input so it falls
// through to the conversational orchestrator.
function resolveSlashCommand(
  text: string,
  clients: Client[],
  lastClientId: string | null | undefined,
): WidgetSpec[] | null {
  const trimmed = text.trim();
  const lower = trimmed.toLowerCase();
  if (!lower.startsWith("/")) return null;

  if (lower.startsWith("/client")) {
    const name = trimmed.slice("/client".length).trim();
    if (!name) return fallback("Usage: /client <name> — e.g. /client Schneider");
    const match = findClient(name, clients);
    if (!match) return fallback(`Client not found: "${name}"`);
    const cid = match.client_id;
    return [
      { component: "DnaCard", props: { clientId: cid } },
      { component: "HoldingsTable", props: { clientId: cid } },
      { component: "DriftBars", props: { clientId: cid } },
    ];
  }

  if (lower.startsWith("/book")) {
    return [{ component: "BookList", props: {} }];
  }

  if (lower.startsWith("/portfolio")) {
    const named = findClient(trimmed.slice("/portfolio".length), clients);
    const cid = named?.client_id ?? lastClientId ?? "";
    if (!cid) {
      return fallback("Select a client first — try /client <name>, then /portfolio analysis.");
    }
    return [
      { component: "AllocationDonut", props: { clientId: cid } },
      { component: "DriftBars", props: { clientId: cid } },
      { component: "FitHeatmap", props: { clientId: cid } },
    ];
  }

  if (lower.startsWith("/note")) {
    const noteText = trimmed.slice("/note".length).trim();
    return fallback(
      noteText ? `Note captured: ${noteText}` : "Speak or type your note after /note",
    );
  }

  return null; // unknown slash → let the orchestrator handle it conversationally
}

export function InputDock({ clients, onAddSpecs, lastClientId }: InputDockProps) {
  const [value, setValue] = useState("");
  const [scope, setScope] = useState<ScopeTab>("all");
  const [loading, setLoading] = useState(false);
  const [hidden, setHidden] = useState(false);
  const historyRef = useRef<ChatTurn[]>([]);
  const { supported, recording, transcript, start, stop } = useVoiceInput();

  // Sync live transcript into the text input so the user can review/edit before submitting
  useEffect(() => {
    if (transcript) setValue(transcript);
  }, [transcript]);

  async function submit(text = value) {
    const query = text.trim();
    if (!query || loading) return;
    setValue("");

    // Fast local path for slash shortcuts.
    const slash = resolveSlashCommand(query, clients, lastClientId);
    if (slash) {
      onAddSpecs(slash);
      return;
    }

    // Conversational path → LLM orchestrator. The user turn renders immediately;
    // the send button shows a spinner while the model thinks.
    onAddSpecs([{ component: "ChatMessage", props: { role: "user", text: query } }]);
    setLoading(true);
    try {
      const res = await postOrchestrate({
        query,
        scope,
        client_id: lastClientId ?? null,
        history: historyRef.current.slice(-8),
      });
      // Replace the pending bubble with the real reply + any widgets.
      onAddSpecs([
        { component: "ChatMessage", props: { role: "assistant", text: res.reply } },
        ...res.specs,
      ]);
      const turns: ChatTurn[] = [
        { role: "user", content: query },
        { role: "assistant", content: res.reply },
      ];
      historyRef.current = [...historyRef.current, ...turns].slice(-12);
    } catch {
      onAddSpecs([
        {
          component: "ChatMessage",
          props: {
            role: "assistant",
            text: "I couldn't reach the workbench just now. Please try again in a moment.",
          },
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  if (hidden) {
    return (
      <div className="border-t border-border bg-panel px-4 py-2">
        <button
          type="button"
          onClick={() => setHidden(false)}
          className="text-[12px] text-muted transition-colors hover:text-text"
        >
          ↑ Show input
        </button>
      </div>
    );
  }

  return (
    <div className="border-t border-border bg-panel px-4 py-2.5">
      {/* Top row: scope tabs + hide toggle */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {SCOPE_TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => setScope(key)}
              className={`rounded-lg border px-2.5 py-0.5 text-[11px] transition-colors ${
                scope === key
                  ? "border-blue/30 bg-blue/10 text-blue"
                  : "border-border text-muted hover:text-text"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setHidden(true)}
          title="Hide input"
          className="shrink-0 text-[11px] text-dim transition-colors hover:text-muted"
        >
          ↓ Hide
        </button>
      </div>

      {/* Quick-command chips */}
      <div className="mb-2 flex flex-wrap gap-1.5">
        {QUICK_COMMANDS.map((cmd) => (
          <button
            key={cmd}
            type="button"
            disabled={loading}
            onClick={() => submit(cmd)}
            className="rounded-lg border border-border px-2.5 py-1 font-mono text-[12px] text-muted transition-colors hover:border-blue hover:text-text disabled:opacity-50"
          >
            {cmd}
          </button>
        ))}
      </div>

      {/* Command input row */}
      <div className="flex items-center gap-2.5 rounded-xl border border-border bg-panel2 px-3 py-2.5">
        <button
          type="button"
          onMouseDown={supported ? start : undefined}
          onMouseUp={supported ? stop : undefined}
          disabled={!supported || loading}
          title={
            !supported
              ? "Voice not supported in this browser"
              : recording
                ? "Release to stop"
                : "Hold to speak"
          }
          aria-label="Voice input"
          className={`text-base transition-colors ${
            !supported
              ? "cursor-not-allowed text-dim opacity-30"
              : recording
                ? "animate-pulse text-blue"
                : "text-muted hover:text-text"
          }`}
        >
          🎙
        </button>
        <input
          value={value}
          disabled={loading}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="Ask anything, or type / for commands…"
          className="flex-1 bg-transparent text-[14px] text-text outline-none placeholder:text-dim disabled:opacity-50"
        />
        <button
          type="button"
          onClick={() => submit()}
          disabled={loading}
          title="Send"
          aria-label="Send"
          className="text-base text-muted transition-colors hover:text-blue disabled:opacity-50"
        >
          {loading ? (
            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-border border-t-blue" />
          ) : (
            "➤"
          )}
        </button>
      </div>
    </div>
  );
}
