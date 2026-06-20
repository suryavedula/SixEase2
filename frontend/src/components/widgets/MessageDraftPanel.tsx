import { useState, useEffect } from "react";
import { getLatestDraft, sendTestDraft } from "../../api/messages";
import type { MessageDraft } from "../../api/messages";
import { SourcesFooter } from "./SourcesFooter";
import type { DisplaySource } from "./SourcesFooter";

type Status =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "ok"; data: MessageDraft }
  | { kind: "error"; message: string };

type SendState =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "sent"; ui: string }
  | { kind: "error"; message: string };

const CHANNEL_ICONS: Record<string, string> = {
  call: "📞",
  email: "✉",
  "in-person": "🤝",
};

const CHANNEL_LABELS: Record<string, string> = {
  call: "Call",
  email: "Email",
  "in-person": "In-person",
};

const CHANNEL_COLORS: Record<string, string> = {
  call: "border-blue/30 bg-blue/10 text-blue",
  email: "border-border bg-panel2 text-muted",
  "in-person": "border-green/30 bg-green/10 text-green",
};

function buildMailtoLink(draft: MessageDraft): string {
  const subject = encodeURIComponent("Advisory Update");
  const rawBody =
    draft.draft_text ??
    (draft.fact_sheet ? JSON.stringify(draft.fact_sheet, null, 2) : "");
  const body =
    rawBody.length > 1800
      ? rawBody.slice(0, 1800) + "…(truncated)"
      : rawBody;
  return `mailto:client@demo.test?subject=${subject}&body=${encodeURIComponent(body)}`;
}

interface MessageDraftPanelProps {
  clientId: string;
}

export function MessageDraftPanel({ clientId }: MessageDraftPanelProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [copied, setCopied] = useState(false);
  const [sendState, setSendState] = useState<SendState>({ kind: "idle" });

  useEffect(() => {
    setStatus({ kind: "loading" });
    setSendState({ kind: "idle" });
    const ctrl = new AbortController();
    getLatestDraft(clientId, ctrl.signal)
      .then((data) => setStatus({ kind: "ok", data }))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        if (message.includes("404")) {
          setStatus({ kind: "empty" });
        } else {
          setStatus({ kind: "error", message });
        }
      });
    return () => ctrl.abort();
  }, [clientId]);

  if (status.kind === "loading") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 space-y-3">
        <div className="h-5 w-40 animate-pulse rounded bg-panel3" />
        <div className="h-10 w-full animate-pulse rounded bg-panel3" />
        <div className="h-20 w-full animate-pulse rounded bg-panel3" />
      </div>
    );
  }

  if (status.kind === "empty") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px] text-muted">
        No draft assembled yet — run{" "}
        <code className="font-mono text-dim">
          POST /admin/assemble/fact-sheet
        </code>{" "}
        first.
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px]">
        <p className="text-muted">Could not load message draft.</p>
        <p className="mt-1 text-[11px] text-dim">{status.message}</p>
      </div>
    );
  }

  const { data } = status;
  const provenanceSources: DisplaySource[] = (data.provenance ?? []).map((entry, i) => ({
    id: `prov-${i}`,
    kind: "CRM" as const,
    label: entry.fact_key,
    detail: `${entry.value} · ${entry.source}`,
    url: null,
    date: null,
  }));
  const channel = data.channel ?? "email";
  const channelColor = CHANNEL_COLORS[channel] ?? CHANNEL_COLORS.email;
  const channelIcon = CHANNEL_ICONS[channel] ?? "✉";
  const channelLabel = CHANNEL_LABELS[channel] ?? channel;
  const hasText = !!data.draft_text;
  const copyText =
    data.draft_text ??
    (data.fact_sheet ? JSON.stringify(data.fact_sheet, null, 2) : "");

  const handleCopy = async () => {
    if (!copyText) return;
    await navigator.clipboard.writeText(copyText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSendTest = async () => {
    setSendState({ kind: "sending" });
    try {
      const res = await sendTestDraft(data.id);
      setSendState({ kind: "sent", ui: res.mailhog_ui });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setSendState({ kind: "error", message });
    }
  };

  return (
    <div className="rounded-[14px] border border-border bg-panel p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-[15px] text-text">
          Message Draft
        </span>
        <span
          className={`flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium ${channelColor}`}
        >
          {channelIcon}
          <span>Suggest: {channelLabel}</span>
        </span>
      </div>

      <div className="rounded-lg border border-border bg-panel2 p-3 min-h-[80px]">
        {hasText ? (
          <p className="text-[12.5px] leading-relaxed text-text whitespace-pre-wrap line-clamp-6">
            {data.draft_text}
          </p>
        ) : (
          <p className="text-[12.5px] text-dim italic">
            Draft not yet generated — run LLM render first (TASK-038).
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <a
          href={buildMailtoLink(data)}
          className="rounded-lg bg-blue/15 px-3 py-1.5 text-[11px] font-medium text-blue transition-colors hover:bg-blue/25"
          title="Open pre-filled draft in your email client"
        >
          Open in Outlook
        </a>
        <button
          type="button"
          onClick={handleCopy}
          disabled={!copyText}
          className="rounded-lg border border-border px-3 py-1.5 text-[11px] text-muted transition-colors hover:text-text disabled:opacity-40"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
        {sendState.kind === "idle" && (
          <button
            type="button"
            onClick={handleSendTest}
            className="rounded-lg border border-border px-3 py-1.5 text-[11px] text-muted transition-colors hover:text-text"
          >
            Send test (MailHog)
          </button>
        )}
        {sendState.kind === "sending" && (
          <button
            type="button"
            disabled
            className="rounded-lg border border-border px-3 py-1.5 text-[11px] text-dim opacity-60"
          >
            Sending…
          </button>
        )}
        {sendState.kind === "sent" && (
          <a
            href={sendState.ui}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-green/30 bg-green/10 px-3 py-1.5 text-[11px] text-green transition-colors hover:bg-green/20"
          >
            Sent — View in MailHog
          </a>
        )}
        {sendState.kind === "error" && (
          <>
            <button
              type="button"
              onClick={handleSendTest}
              className="rounded-lg border border-border px-3 py-1.5 text-[11px] text-muted transition-colors hover:text-text"
            >
              Retry send
            </button>
            <p className="w-full text-[11px] text-red">{sendState.message}</p>
          </>
        )}
      </div>

      <SourcesFooter sources={provenanceSources} />

      <p className="text-[10.5px] text-dim">
        Draft only — nothing auto-sends. You review and send from your own
        identity.
      </p>
    </div>
  );
}
