// Bottom input dock (TASK-042, TASK-043, TASK-046). Slash-command / NL / voice entry.
//
// Two paths:
//   • Slash commands (/client, /book, /portfolio, /note) resolve locally and
//     instantly — deterministic view-summons for power users.
//   • Everything else is a real conversation: the query goes to the LLM
//     orchestrator (/orchestrate), which replies and picks generative-UI widgets.
//     User + assistant turns render as chat bubbles in the canvas, interleaved
//     with the widgets, and recent turns are sent back as context.

import { useRef, useState } from "react";
import {
  Activity,
  GitCompareArrows,
  PieChart,
  ShieldCheck,
  Users,
} from "lucide-react";
import { useAudioRecorder } from "../../hooks/useAudioRecorder";
import { postTranscribe, transcribeDictation } from "../../api/notes";
import { postOrchestrate, type ChatTurn } from "../../api/orchestrate";
import type { WidgetSpec } from "../../registry/types";
import { useCanvasActions } from "./CanvasActions";
import { useToast } from "../../context/ToastProvider";

// One-click dashboard shortcuts — open a widget view without typing. Book-level
// shortcuts always work. Client-scoped ones target the client in focus; with none
// selected they open the client book as a picker (`pick`) — each row jumps into
// that shortcut's view for the chosen client.
const SHORTCUTS: {
  key: string;
  label: string;
  Icon: typeof Activity;
  build: (clientId: string) => WidgetSpec[];
  // When no client is in focus, open the book as a picker into this widget.
  pick?: string;
}[] = [
  {
    key: "radar",
    label: "Radar",
    Icon: Activity,
    build: () => [{ component: "ChangeRadar", props: {} }],
  },
  {
    key: "clients",
    label: "Clients",
    Icon: Users,
    build: () => [{ component: "ClientBook", props: {} }],
  },
  {
    key: "portfolio",
    label: "Portfolio",
    Icon: PieChart,
    build: (cid) => [{ component: "PortfolioView", props: { clientId: cid } }],
    pick: "PortfolioView",
  },
  {
    key: "values",
    label: "Values",
    Icon: ShieldCheck,
    build: (cid) => [
      { component: "DnaCard", props: { clientId: cid } },
      { component: "ConflictsList", props: { clientId: cid } },
    ],
    pick: "DnaCard",
  },
  {
    key: "rebalance",
    label: "Rebalance",
    Icon: GitCompareArrows,
    build: (cid) => [{ component: "BeforeAfter", props: { clientId: cid } }],
    pick: "BeforeAfter",
  },
];

// "Ask the AI" starters reflecting an RM's daily triage — navigation lives in the
// shortcut row above, so these are conversational questions that surface what
// matters: who's at risk, who's furthest off, a client's values story, prep.
// Each maps to something the orchestrator reliably renders (filtered book or a
// named-client view).
const QUICK_COMMANDS = [
  "Which clients have values conflicts?",
  "Who's furthest from their values fit?",
  "How does Schneider's portfolio fit her values?",
  "Prep me for my meeting with Huber",
] as const;

// Map the recorder's MIME type to a filename extension Whisper recognises.
function filenameForBlob(blob: Blob): string {
  const t = blob.type;
  if (t.includes("mp4")) return "dictation.mp4";
  if (t.includes("ogg")) return "dictation.ogg";
  if (t.includes("wav")) return "dictation.wav";
  return "dictation.webm";
}

interface Client {
  client_id: string;
  client_name: string;
}

interface InputDockProps {
  clients: Client[];
  onAddSpecs: (specs: WidgetSpec[]) => void;
  lastClientId?: string | null;
}

// A resolved slash command is either widgets to render or an error to surface.
type SlashResult =
  | { kind: "specs"; specs: WidgetSpec[] }
  | { kind: "openClient"; clientId: string }
  | { kind: "error"; message: string };

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

// Slash-command catalogue — drives the autocomplete dropdown so the commands are
// discoverable instead of memorised.
const COMMANDS: { cmd: string; usage: string; hint: string }[] = [
  { cmd: "/client", usage: "/client <name>", hint: "Open a client" },
  { cmd: "/book", usage: "/book", hint: "Browse all clients" },
  { cmd: "/portfolio", usage: "/portfolio [name]", hint: "View a portfolio" },
  { cmd: "/note", usage: "/note [text]", hint: "Capture a note" },
];

interface SlashSuggestion {
  key: string;
  primary: string;
  secondary: string;
  insert: string; // text to place in the input
  submit: boolean; // run immediately on select (vs. just complete the text)
}

// Suggestions for the current input: command names while typing "/xxx", then
// client names once a /client or /portfolio command has a space.
function slashSuggestions(value: string, clients: Client[]): SlashSuggestion[] {
  if (!value.startsWith("/")) return [];
  const spaceIdx = value.indexOf(" ");
  if (spaceIdx === -1) {
    const q = value.toLowerCase();
    return COMMANDS.filter((c) => c.cmd.startsWith(q)).map((c) => ({
      key: c.cmd,
      primary: c.usage,
      secondary: c.hint,
      insert: c.cmd === "/book" ? c.cmd : `${c.cmd} `,
      submit: c.cmd === "/book", // /book takes no argument → run it
    }));
  }
  const cmd = value.slice(0, spaceIdx).toLowerCase();
  if (cmd === "/client" || cmd === "/portfolio") {
    const q = value.slice(spaceIdx + 1).trim().toLowerCase();
    return clients
      .filter((c) => !q || c.client_name.toLowerCase().includes(q))
      .slice(0, 6)
      .map((c) => ({
        key: c.client_id,
        primary: c.client_name,
        secondary: cmd === "/client" ? "Open client" : "Open portfolio",
        insert: `${cmd} ${c.client_name}`,
        submit: true,
      }));
  }
  return [];
}

// Resolve a slash command locally. Returns null for non-slash input so it falls
// through to the conversational orchestrator.
function resolveSlashCommand(
  text: string,
  clients: Client[],
  lastClientId: string | null | undefined,
): SlashResult | null {
  const trimmed = text.trim();
  const lower = trimmed.toLowerCase();
  if (!lower.startsWith("/")) return null;

  if (lower.startsWith("/client")) {
    const name = trimmed.slice("/client".length).trim();
    if (!name)
      return { kind: "error", message: "Usage: /client <name> — e.g. /client Schneider" };
    const match = findClient(name, clients);
    if (!match) return { kind: "error", message: `Client not found: "${name}"` };
    // Open in the RM's preferred default view (handled by the caller via openClient).
    return { kind: "openClient", clientId: match.client_id };
  }

  if (lower.startsWith("/book")) {
    return { kind: "specs", specs: [{ component: "ClientBook", props: {} }] };
  }

  if (lower.startsWith("/portfolio")) {
    const named = findClient(trimmed.slice("/portfolio".length), clients);
    const cid = named?.client_id ?? lastClientId ?? "";
    if (!cid) {
      // No client resolved → open the book as a portfolio picker to choose one.
      return {
        kind: "specs",
        specs: [
          {
            component: "ClientBook",
            props: { title: "Select a client — Portfolio", openComponent: "PortfolioView" },
          },
        ],
      };
    }
    return { kind: "specs", specs: [{ component: "PortfolioView", props: { clientId: cid } }] };
  }

  if (lower.startsWith("/note")) {
    const noteText = trimmed.slice("/note".length).trim();
    return {
      kind: "specs",
      specs: [
        {
          component: "VoiceNoteWidget",
          props: {
            transcript: noteText || undefined,
            clientId: lastClientId ?? undefined,
          },
        },
      ],
    };
  }

  return null; // unknown slash → let the orchestrator handle it conversationally
}

export function InputDock({ clients, onAddSpecs, lastClientId }: InputDockProps) {
  const { openClient } = useCanvasActions();
  const { toast } = useToast();
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const historyRef = useRef<ChatTurn[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const recorder = useAudioRecorder();
  const [transcribing, setTranscribing] = useState(false);
  // Slash-command autocomplete state.
  const [activeIdx, setActiveIdx] = useState(0);
  const [suppressSuggest, setSuppressSuggest] = useState(false);
  const suggestions = suppressSuggest ? [] : slashSuggestions(value, clients);
  const showSuggest = suggestions.length > 0;

  function applySuggestion(s: SlashSuggestion) {
    if (s.submit) {
      setSuppressSuggest(true);
      submit(s.insert);
    } else {
      setValue(s.insert);
      setActiveIdx(0);
      inputRef.current?.focus();
    }
  }

  // Click to toggle: click to start, click again to stop. On stop the clip is
  // stored + Whisper-transcribed (local, no cloud), then opened as a voice note
  // (VoiceNoteWidget) where the agent structures it into note + DNA + tasks.
  // (Click-start/stop — a hold gesture races the async mic grant and captures an
  // empty clip.)
  async function toggleMic() {
    if (transcribing) return;
    if (recorder.recording) {
      const blob = await recorder.stop();
      if (!blob || blob.size < 1200) {
        setError("Recording too short — try again.");
        return;
      }
      setTranscribing(true);
      try {
        if (lastClientId) {
          // Client in focus → store the clip + transcribe, open the note for it.
          const res = await postTranscribe(lastClientId, blob, filenameForBlob(blob));
          onAddSpecs([
            {
              component: "VoiceNoteWidget",
              props: { transcript: res.transcript, audioKey: res.audio_key, clientId: lastClientId },
            },
          ]);
        } else {
          // No client yet → transcribe, open the note card with a client picker.
          const text = await transcribeDictation(blob, filenameForBlob(blob));
          onAddSpecs([
            { component: "VoiceNoteWidget", props: { transcript: text, clients } },
          ]);
        }
      } catch (err) {
        setError((err as Error).message ?? "Transcription failed");
      } finally {
        setTranscribing(false);
      }
    } else {
      setError(null);
      await recorder.start();
    }
  }

  // Run a one-click shortcut. With no client in focus, a client-scoped shortcut
  // opens the client book as a picker into its view — pick a client, land there.
  function runShortcut(s: (typeof SHORTCUTS)[number]) {
    setError(null);
    if (s.pick && !lastClientId) {
      onAddSpecs([
        {
          component: "ClientBook",
          props: { title: `Select a client — ${s.label}`, openComponent: s.pick },
        },
      ]);
      return;
    }
    onAddSpecs(s.build(lastClientId ?? ""));
  }

  async function submit(text = value) {
    const query = text.trim();
    if (!query || loading) return;
    setValue("");
    setError(null);

    // Fast local path for slash shortcuts.
    const slash = resolveSlashCommand(query, clients, lastClientId);
    if (slash) {
      if (slash.kind === "error") {
        setError(slash.message);
      } else if (slash.kind === "openClient") {
        openClient(slash.clientId);
        const c = clients.find((x) => x.client_id === slash.clientId);
        toast({ message: `Opened ${c?.client_name ?? "client"}` });
      } else {
        onAddSpecs(slash.specs);
      }
      setSuppressSuggest(false);
      return;
    }

    // Conversational path → LLM orchestrator. The user turn renders immediately;
    // the send button shows a spinner while the model thinks.
    onAddSpecs([{ component: "ChatMessage", props: { role: "user", text: query } }]);
    setLoading(true);
    try {
      const res = await postOrchestrate({
        query,
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
      toast({
        message: "Couldn't reach the workbench",
        action: { label: "Retry", onClick: () => submit(query) },
      });
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
      {/* Top row: one-click dashboard shortcuts + hide toggle */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {SHORTCUTS.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => runShortcut(s)}
              title={`Open ${s.label}`}
              className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-0.5 text-[11px] text-muted transition-colors hover:border-blue hover:text-text"
            >
              <s.Icon className="h-3.5 w-3.5" />
              {s.label}
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

      {/* Inline error — explicit, dismissed on the next action */}
      {error && (
        <div className="mb-2 flex items-start gap-2 rounded-lg border border-red/30 bg-red/10 px-2.5 py-1.5 text-[11.5px] text-red">
          <span className="flex-1">{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="shrink-0 text-red/70 transition-colors hover:text-red"
            aria-label="Dismiss error"
          >
            ×
          </button>
        </div>
      )}

      {/* Quick-command chips */}
      <div className="mb-2 flex flex-wrap gap-1.5">
        {QUICK_COMMANDS.map((cmd) => (
          <button
            key={cmd}
            type="button"
            disabled={loading}
            onClick={() => submit(cmd)}
            className="rounded-lg border border-border px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-blue hover:text-text disabled:opacity-50"
          >
            {cmd}
          </button>
        ))}
      </div>

      {/* Command input row */}
      <div className="relative flex items-center gap-2.5 rounded-xl border border-border bg-panel2 px-3 py-2.5">
        {/* Slash-command autocomplete */}
        {showSuggest && (
          <div className="absolute bottom-full left-0 right-0 mb-1.5 overflow-hidden rounded-xl border border-border bg-panel2 shadow-lg">
            {suggestions.map((s, i) => (
              <button
                key={s.key}
                type="button"
                // mousedown (not click) so it fires before the input blurs.
                onMouseDown={(e) => {
                  e.preventDefault();
                  applySuggestion(s);
                }}
                onMouseEnter={() => setActiveIdx(i)}
                className={`flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left text-[12px] transition-colors ${
                  i === activeIdx ? "bg-blue/10 text-text" : "text-muted"
                }`}
              >
                <span className="font-medium">{s.primary}</span>
                <span className="text-[11px] text-dim">{s.secondary}</span>
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          onClick={recorder.supported ? toggleMic : undefined}
          disabled={!recorder.supported || loading || transcribing}
          title={
            !recorder.supported
              ? "Recording not supported in this browser"
              : transcribing
                ? "Transcribing…"
                : recorder.recording
                  ? "Click to stop & transcribe"
                  : "Click to record"
          }
          aria-label="Voice input"
          className={`text-base transition-colors ${
            !recorder.supported
              ? "cursor-not-allowed text-dim opacity-30"
              : recorder.recording || transcribing
                ? "animate-pulse text-blue"
                : "text-muted hover:text-text"
          }`}
        >
          {transcribing ? (
            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-border border-t-blue" />
          ) : (
            "🎙"
          )}
        </button>
        <input
          ref={inputRef}
          value={value}
          disabled={loading}
          onChange={(e) => {
            setValue(e.target.value);
            setActiveIdx(0);
            setSuppressSuggest(false);
          }}
          onKeyDown={(e) => {
            if (showSuggest) {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActiveIdx((i) => (i + 1) % suggestions.length);
                return;
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setActiveIdx((i) => (i - 1 + suggestions.length) % suggestions.length);
                return;
              }
              if (e.key === "Enter" || e.key === "Tab") {
                e.preventDefault();
                applySuggestion(suggestions[activeIdx]);
                return;
              }
              if (e.key === "Escape") {
                e.preventDefault();
                setSuppressSuggest(true);
                return;
              }
            }
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
