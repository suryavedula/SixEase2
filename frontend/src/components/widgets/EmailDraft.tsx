import { useCallback, useEffect, useState } from "react";
import { Check, Copy, RefreshCw, Send, ShieldCheck } from "lucide-react";
import {
  approveDraft,
  generateDraft,
  getDraft,
  getLatestDraft,
  patchDraftText,
  sendTestDraft,
  triggerRender,
  type MessageDraft,
} from "../../api/messages";
import { cn } from "../../lib/utils";
import { WidgetContainer } from "./WidgetContainer";

// Ported from Kielis_Advisor_workbech EmailDraftCanvas, re-tokenised + wired to
// the real messages API. Everything is live, not mocked:
//   • the tone toggle calls triggerRender → the LLM re-writes the draft in that
//     preset (data-driven / values-led / balanced) — no fabricated tone variants.
//   • "Locked Facts" is the draft's real provenance (fact → value → source).
//   • Save = patchDraftText, Approve = approveDraft, Send test = MailHog.
// Nothing auto-sends; approval only marks the draft for the RM.

const PRESETS = ["data-driven", "values-led", "balanced"] as const;
type Preset = (typeof PRESETS)[number];

// `style` may be a plain preset string or the full style-profile object ({preset}).
function presetOf(style: MessageDraft["style"]): string {
  if (typeof style === "string") return style.toLowerCase();
  if (style && typeof style === "object") return String(style.preset ?? "").toLowerCase();
  return "";
}

type Status =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "error"; message: string }
  | { kind: "ok"; draft: MessageDraft };

interface EmailDraftProps {
  clientId: string;
  // When opened from an alert, target that alert's conflict for fact assembly.
  alertId?: string;
  // When opened from a prepared answer (email auto-draft), load that exact draft.
  draftId?: string;
}

export function EmailDraft({ clientId, alertId, draftId }: EmailDraftProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<null | "saving" | "approving" | "sending" | "generating" | Preset>(null);
  const [copied, setCopied] = useState(false);
  const [sentUi, setSentUi] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  const load = useCallback(
    (signal?: AbortSignal) => {
      setStatus({ kind: "loading" });
      // A specific prepared-answer draft loads by id; otherwise the client's latest.
      (draftId ? getDraft(draftId, signal) : getLatestDraft(clientId, signal))
        .then((draft) => {
          if (signal?.aborted) return;
          setStatus({ kind: "ok", draft });
          setText(draft.draft_text ?? "");
          setApproved(draft.status === "approved");
        })
        .catch((err: unknown) => {
          if (signal?.aborted) return;
          const message = err instanceof Error ? err.message : String(err);
          setStatus(message.includes("404") ? { kind: "empty" } : { kind: "error", message });
        });
    },
    [clientId, draftId],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    setSentUi(null);
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  // Assemble + LLM-render a fresh draft, then show it. Explicit RM action (the
  // only step that spends LLM budget), so it's a button, never automatic.
  const generate = useCallback(async () => {
    setBusy("generating");
    setGenError(null);
    try {
      const draft = await generateDraft(clientId, alertId);
      setStatus({ kind: "ok", draft });
      setText(draft.draft_text ?? "");
      setApproved(draft.status === "approved");
    } catch (err: unknown) {
      setGenError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [clientId, alertId]);

  if (status.kind === "loading") {
    return <div className="h-96 animate-pulse rounded-2xl bg-panel2" />;
  }
  if (status.kind === "empty") {
    return (
      <WidgetContainer title="Communication Draft" source="Generative Engine">
        <p className="text-[13px] text-muted">
          No draft for this client yet. Assemble the grounded fact sheet and write
          a first draft — nothing sends; you review and approve.
        </p>
        <button
          type="button"
          disabled={busy === "generating"}
          onClick={generate}
          className="mt-3 flex items-center gap-2 rounded-lg bg-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue/90 disabled:opacity-50"
        >
          {busy === "generating" ? (
            <>
              <RefreshCw className="h-4 w-4 animate-spin" /> Generating…
            </>
          ) : (
            "Generate draft"
          )}
        </button>
        {genError && (
          <p className="mt-2 text-[11px] text-red">Could not generate: {genError}</p>
        )}
      </WidgetContainer>
    );
  }
  if (status.kind === "error") {
    return (
      <WidgetContainer title="Communication Draft" source="Generative Engine">
        <p className="text-[13px] text-muted">Could not load the draft.</p>
        <p className="mt-1 text-[11px] text-dim">{status.message}</p>
      </WidgetContainer>
    );
  }

  const { draft } = status;
  const dirty = text !== (draft.draft_text ?? "");
  const provenance = draft.provenance ?? [];

  async function rewriteAs(preset: Preset) {
    setBusy(preset);
    try {
      await triggerRender(draft.id, preset);
      load();
    } catch {
      setBusy(null);
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    setBusy("saving");
    try {
      const updated = await patchDraftText(draft.id, text);
      setStatus({ kind: "ok", draft: updated });
    } catch {
      /* keep edits in the box on failure */
    } finally {
      setBusy(null);
    }
  }

  async function approve() {
    setBusy("approving");
    try {
      await approveDraft(draft.id);
      setApproved(true);
    } catch {
      /* no-op */
    } finally {
      setBusy(null);
    }
  }

  async function sendTest() {
    setBusy("sending");
    try {
      const res = await sendTestDraft(draft.id);
      setSentUi(res.mailhog_ui);
    } catch {
      /* no-op */
    } finally {
      setBusy(null);
    }
  }

  async function copy() {
    if (!text) return;
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-text">Communication Draft</h2>
        <p className="text-sm text-muted">
          Channel: {draft.channel ?? "email"} • nothing sends without your approval
        </p>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* Composer */}
        <div className="min-w-0 flex-1">
          <WidgetContainer title="Email Composer" source="Generative Engine">
            <div className="flex flex-col gap-4">
              {/* Tone presets — real LLM re-render */}
              <div className="flex flex-wrap gap-2 border-b border-border pb-4">
                {PRESETS.map((p) => {
                  const active = presetOf(draft.style) === p;
                  return (
                    <button
                      key={p}
                      type="button"
                      disabled={busy !== null}
                      onClick={() => rewriteAs(p)}
                      className={cn(
                        "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium capitalize transition-colors disabled:opacity-50",
                        active
                          ? "border-blue/50 bg-blue/15 text-blue"
                          : "border-border bg-panel2 text-muted hover:text-text",
                      )}
                    >
                      {busy === p && <RefreshCw className="h-3 w-3 animate-spin" />}
                      {p}
                    </button>
                  );
                })}
                <span className="ml-auto self-center text-[11px] text-dim">
                  Tone re-writes the draft from the locked facts
                </span>
              </div>

              <div className="flex flex-col gap-2 rounded-xl border border-border bg-panel2 p-4">
                <div className="flex border-b border-border pb-2 text-sm">
                  <span className="w-16 text-dim">Subject:</span>
                  <span className="text-text">Portfolio Update — Action Required</span>
                </div>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  disabled={busy !== null}
                  className="min-h-[260px] w-full resize-none bg-transparent text-sm leading-relaxed text-text outline-none disabled:opacity-60"
                />
              </div>

              <div className="flex flex-wrap gap-3">
                {approved ? (
                  <span className="flex items-center gap-2 rounded-lg border border-green/30 bg-green/10 px-4 py-2.5 text-sm font-medium text-green">
                    <Check className="h-4 w-4" /> Approved
                  </span>
                ) : (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={approve}
                    className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue/90 disabled:opacity-50 sm:flex-none sm:px-5"
                  >
                    <Check className="h-4 w-4" /> {busy === "approving" ? "Approving…" : "Approve"}
                  </button>
                )}
                {dirty && (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={save}
                    className="rounded-lg border border-border bg-panel2 px-4 py-2.5 text-sm font-medium text-text transition-colors hover:bg-panel3 disabled:opacity-50"
                  >
                    {busy === "saving" ? "Saving…" : "Save edits"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={copy}
                  className="flex items-center gap-2 rounded-lg border border-border bg-panel2 px-4 py-2.5 text-sm font-medium text-text transition-colors hover:bg-panel3"
                >
                  <Copy className="h-4 w-4" /> {copied ? "Copied" : "Copy"}
                </button>
                {sentUi ? (
                  <a
                    href={sentUi}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-2 rounded-lg border border-green/30 bg-green/10 px-4 py-2.5 text-sm font-medium text-green"
                  >
                    <Send className="h-4 w-4" /> View in MailHog
                  </a>
                ) : (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={sendTest}
                    className="flex items-center gap-2 rounded-lg border border-border bg-panel2 px-4 py-2.5 text-sm font-medium text-text transition-colors hover:bg-panel3 disabled:opacity-50"
                  >
                    <Send className="h-4 w-4" /> {busy === "sending" ? "Sending…" : "Send test"}
                  </button>
                )}
              </div>
            </div>
          </WidgetContainer>
        </div>

        {/* Locked facts — real provenance */}
        <div className="w-full shrink-0 lg:w-[320px]">
          <WidgetContainer
            title="Locked Facts"
            source="Compliance Guard"
            badges={<ShieldCheck className="h-3.5 w-3.5 text-green" />}
          >
            {provenance.length ? (
              <ul className="space-y-3">
                {provenance.map((p, i) => (
                  <li
                    key={`${p.fact_key}-${i}`}
                    className="rounded-lg border border-green/20 bg-green/5 p-2.5"
                  >
                    <div className="flex items-start gap-2 text-sm text-text">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-green" />
                      <span>{p.value}</span>
                    </div>
                    <div className="mt-1 pl-6 text-[11px] text-dim">
                      {p.fact_key} · {p.source}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">
                No locked facts recorded — the draft is not yet grounded to sources.
              </p>
            )}
            <p className="mt-3 border-t border-border pt-3 text-[11px] text-dim">
              The model may only use these facts. Figures are never invented.
            </p>
          </WidgetContainer>
        </div>
      </div>
    </div>
  );
}
