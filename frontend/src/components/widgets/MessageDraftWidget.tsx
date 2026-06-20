import { useState, useEffect, useCallback } from "react";
import {
  getDraft,
  patchDraftText,
  approveDraft,
  triggerRender,
} from "../../api/messages";
import type { MessageDraft, ProvenanceEntry } from "../../api/messages";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: MessageDraft }
  | { kind: "error"; message: string };

function channelBadge(channel: string | null) {
  if (channel === "call") return "📞 Call";
  if (channel === "email") return "✉ Email";
  if (channel === "in-person") return "🤝 In-person";
  return channel ?? "Channel TBD";
}

function channelChipClass(channel: string | null) {
  if (channel === "call") return "bg-amber/10 text-amber border-amber/30";
  if (channel === "email") return "bg-blue/10 text-blue border-blue/30";
  if (channel === "in-person") return "bg-teal/10 text-teal border-teal/30";
  return "bg-panel3 text-dim border-border";
}

function statusChipClass(status: string) {
  if (status === "approved") return "bg-green/10 text-green border-green/30";
  if (status === "sent") return "bg-teal/10 text-teal border-teal/30";
  if (status === "dismissed") return "bg-red/10 text-red border-red/30";
  return "bg-panel3 text-muted border-border";
}

function activeStylePreset(style: string | null): "data-driven" | "values-led" | null {
  if (!style) return null;
  const lower = style.toLowerCase();
  if (lower.includes("data")) return "data-driven";
  if (lower.includes("values")) return "values-led";
  return null;
}

interface MessageDraftWidgetProps {
  draftId: string;
}

export function MessageDraftWidget({ draftId }: MessageDraftWidgetProps) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [editMode, setEditMode] = useState(false);
  const [editText, setEditText] = useState("");
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [expandedChip, setExpandedChip] = useState<string | null>(null);
  const [provenanceOpen, setProvenanceOpen] = useState(false);
  const [renderPending, setRenderPending] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);

  const fetchDraft = useCallback(
    (signal?: AbortSignal) => {
      setStatus({ kind: "loading" });
      getDraft(draftId, signal)
        .then((data) => setStatus({ kind: "ok", data }))
        .catch((err: unknown) => {
          if (signal?.aborted) return;
          const message = err instanceof Error ? err.message : String(err);
          setStatus({ kind: "error", message });
        });
    },
    [draftId],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    fetchDraft(ctrl.signal);
    return () => ctrl.abort();
  }, [fetchDraft]);

  if (status.kind === "loading") {
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 space-y-3">
        <div className="h-5 w-44 animate-pulse rounded bg-panel3" />
        <div className="h-20 w-full animate-pulse rounded bg-panel3" />
        <div className="h-8 w-full animate-pulse rounded bg-panel3" />
      </div>
    );
  }

  if (status.kind === "error") {
    const is404 = status.message.includes("404");
    return (
      <div className="rounded-[14px] border border-border bg-panel p-4 text-[13px]">
        {is404 ? (
          <p className="text-muted">
            No draft found — run{" "}
            <code className="font-mono text-dim">POST /admin/assemble/fact-sheet</code>{" "}
            first.
          </p>
        ) : (
          <>
            <p className="text-muted">Could not load advisory draft.</p>
            <p className="mt-1 text-dim text-[11px]">{status.message}</p>
          </>
        )}
      </div>
    );
  }

  const draft = status.data;
  const activePreset = activeStylePreset(draft.style);

  async function handleStyleToggle(preset: "data-driven" | "values-led") {
    if (renderPending) return;
    setRenderPending(true);
    setRenderError(null);
    try {
      await triggerRender(draftId, preset);
      fetchDraft();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("404") || msg.includes("500") || msg.includes("422")) {
        setRenderError("LLM render not available yet — run POST /admin/render/message");
      } else {
        setRenderError(msg);
      }
    } finally {
      setRenderPending(false);
    }
  }

  function handleEditStart() {
    setEditText(draft.draft_text ?? "");
    setEditMode(true);
  }

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await patchDraftText(draftId, editText);
      setStatus({ kind: "ok", data: updated });
      setEditMode(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setRenderError(message);
    } finally {
      setSaving(false);
    }
  }

  async function handleApprove() {
    setApproving(true);
    try {
      const res = await approveDraft(draftId);
      setStatus({ kind: "ok", data: { ...draft, status: res.status } });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setRenderError(message);
    } finally {
      setApproving(false);
    }
  }

  const mailtoHref = draft.draft_text
    ? `mailto:?subject=${encodeURIComponent("Advisory Draft")}&body=${encodeURIComponent(draft.draft_text.slice(0, 1800))}`
    : undefined;

  const provenance = (draft.provenance ?? []) as ProvenanceEntry[];
  const factsUsed = (draft.facts_used ?? []) as string[];

  return (
    <div className="rounded-[14px] border border-border bg-panel p-4">
      {/* ── Header ── */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="font-semibold text-[15px] text-text flex-1">
          Advisory Draft
        </span>

        {/* Channel badge */}
        <span
          className={`rounded border px-2 py-0.5 text-[11px] font-semibold ${channelChipClass(draft.channel)}`}
        >
          {channelBadge(draft.channel)}
        </span>

        {/* Status chip */}
        <span
          className={`rounded border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${statusChipClass(draft.status)}`}
        >
          {draft.status}
        </span>
      </div>

      {/* ── Style toggle ── */}
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[11px] text-dim uppercase tracking-wider shrink-0">
          Style
        </span>
        {(["data-driven", "values-led"] as const).map((preset) => (
          <button
            key={preset}
            type="button"
            disabled={renderPending}
            onClick={() => handleStyleToggle(preset)}
            className={`rounded border px-2.5 py-1 text-[11px] transition-colors ${
              activePreset === preset
                ? "border-blue/30 bg-blue/15 text-blue"
                : "border-border text-muted hover:text-text"
            } disabled:opacity-50`}
          >
            {preset === "data-driven" ? "Data-driven" : "Values-led"}
            {renderPending && activePreset !== preset && " ⟳"}
          </button>
        ))}
        {renderError && (
          <span className="text-[11px] text-amber ml-1">{renderError}</span>
        )}
      </div>

      {/* ── Draft body ── */}
      <div className="mb-4">
        {draft.draft_text === null ? (
          <div className="rounded-lg border border-border bg-panel2 px-3 py-3 text-[13px] text-muted italic">
            Draft not yet generated — toggle a style above or run{" "}
            <code className="not-italic font-mono text-dim text-[11px]">
              POST /admin/render/message?draft_id={draftId}
            </code>
          </div>
        ) : editMode ? (
          <div className="space-y-2">
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={10}
              className="w-full rounded-lg border border-border bg-panel2 px-3 py-2 text-[13px] text-text leading-relaxed outline-none resize-y focus:border-blue/50 transition-colors"
            />
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="rounded-lg bg-blue/15 px-3 py-1 text-[11px] font-medium text-blue hover:bg-blue/25 transition-colors disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={() => setEditMode(false)}
                className="rounded-lg border border-border px-3 py-1 text-[11px] text-muted hover:text-text transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <pre className="whitespace-pre-wrap text-[13px] text-muted leading-relaxed rounded-lg border border-border bg-panel2 px-3 py-3 font-sans overflow-auto max-h-[320px]">
            {draft.draft_text}
          </pre>
        )}
      </div>

      {/* ── Provenance panel ── */}
      <div className="mb-4 border-t border-border pt-3">
        <button
          type="button"
          onClick={() => setProvenanceOpen((o) => !o)}
          className="text-[12px] text-muted hover:text-text transition-colors"
        >
          {provenanceOpen ? "▲" : "▼"} Provenance
          {provenance.length > 0 && ` · ${provenance.length} sources`}
        </button>

        {provenanceOpen && (
          <div className="mt-2">
            {provenance.length === 0 ? (
              <p className="text-[12px] text-dim italic">
                No provenance yet — render draft to populate.
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {provenance.map((entry, i) => {
                  const key = `prov:${i}`;
                  const isOpen = expandedChip === key;
                  return (
                    <div key={i}>
                      <button
                        type="button"
                        onClick={() => setExpandedChip(isOpen ? null : key)}
                        className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] transition-colors bg-blue/10 text-blue border-blue/20 hover:bg-blue/15 ${isOpen ? "ring-1 ring-blue/40" : ""}`}
                      >
                        {entry.fact_key}
                      </button>
                      {isOpen && (
                        <div className="mt-1.5 rounded-lg border border-border bg-panel2 p-2.5 text-[12px]">
                          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-dim">
                            Value
                          </div>
                          <p className="text-muted mb-1.5 leading-snug">{entry.value}</p>
                          <div className="text-[10px] font-semibold uppercase tracking-wider text-dim">
                            Source
                          </div>
                          <p className="text-dim text-[11px]">{entry.source}</p>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {factsUsed.length > 0 && (
              <div className="mt-2">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-dim mb-1">
                  Facts cited
                </p>
                <ul className="space-y-0.5">
                  {factsUsed.map((key) => (
                    <li key={key} className="font-mono text-[11px] text-dim">
                      {key}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Action bar ── */}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={handleApprove}
          disabled={draft.status === "approved" || approving}
          className="rounded-lg bg-blue/15 px-2.5 py-1 text-[11px] font-medium text-blue hover:bg-blue/25 transition-colors disabled:opacity-40"
        >
          {approving ? "Approving…" : draft.status === "approved" ? "Approved ✓" : "Approve"}
        </button>

        {!editMode && draft.status !== "approved" && (
          <button
            type="button"
            onClick={handleEditStart}
            className="rounded-lg border border-border px-2.5 py-1 text-[11px] text-muted hover:text-text transition-colors"
          >
            Edit
          </button>
        )}

        {mailtoHref ? (
          <a
            href={mailtoHref}
            className="rounded-lg border border-teal/30 bg-teal/10 px-2.5 py-1 text-[11px] text-teal hover:bg-teal/15 transition-colors"
          >
            Handoff · {channelBadge(draft.channel)}
          </a>
        ) : (
          <span className="rounded-lg border border-border px-2.5 py-1 text-[11px] text-dim opacity-50 cursor-not-allowed">
            Handoff (draft pending)
          </span>
        )}
      </div>
    </div>
  );
}
