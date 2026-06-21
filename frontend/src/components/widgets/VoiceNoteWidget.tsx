// Voice note widget (TASK-047, EPIC-11).
// Full capture-to-commit flow: record audio → Whisper transcript (editable) →
// structure into a CRM note + DNA proposals + task proposals → RM approves
// before anything is saved (G1). The RM can also type a transcript directly.

import { useEffect, useRef, useState } from "react";
import { postNoteStructure, postNoteCommit, postTranscribe, transcribeDictation } from "../../api/notes";
import type { DNAProposal, EventProposal, NoteStructureResponse, TaskProposal } from "../../api/notes";
import { createTask } from "../../api/tasks";
import { useAudioRecorder } from "../../hooks/useAudioRecorder";

interface VoiceNoteClient {
  client_id: string;
  client_name: string;
}

interface VoiceNoteWidgetProps {
  transcript?: string;
  clientId?: string;
  audioKey?: string;  // MinIO key when the recording was already stored (dock mic)
  clients?: VoiceNoteClient[];  // for the in-card picker when no client is in focus
}

// Map the recorder's MIME type to a filename extension Whisper recognises.
function filenameForBlob(blob: Blob): string {
  const t = blob.type;
  if (t.includes("mp4")) return "recording.mp4";
  if (t.includes("ogg")) return "recording.ogg";
  if (t.includes("wav")) return "recording.wav";
  return "recording.webm";
}

const DNA_CATEGORY_STYLE: Record<string, { label: string; cls: string }> = {
  values:       { label: "Value",      cls: "bg-blue/10 text-blue border-blue/20" },
  exclusions:   { label: "Exclusion",  cls: "bg-red/10 text-red border-red/20" },
  tilts:        { label: "Tilt",       cls: "bg-amber/10 text-amber border-amber/20" },
  life_events:  { label: "Life event", cls: "bg-violet/10 text-violet border-violet/20" },
  promises:     { label: "Promise",    cls: "bg-green/10 text-green border-green/20" },
};

type Status =
  | { kind: "no-client" }
  | { kind: "capture" }       // record audio or type a transcript
  | { kind: "transcribing" }  // Whisper running on the uploaded clip
  | { kind: "review" }        // editable transcript, before structuring
  | { kind: "structuring" }
  | { kind: "draft" }
  | { kind: "committing" }
  | { kind: "done"; taskCount: number }
  | { kind: "error"; message: string };

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function VoiceNoteWidget({ transcript, clientId, audioKey: audioKeyProp, clients }: VoiceNoteWidgetProps) {
  const [status, setStatus] = useState<Status>(() => {
    // A transcript (typed via `/note`, or recorded from the dock mic) lands in
    // review — the RM edits it and, if no client is in focus, picks one there.
    if (transcript) return { kind: "review" };
    if (clientId) return { kind: "capture" };
    return { kind: "no-client" };
  });

  // The note's client: the prop when a client is in focus, else the RM's pick
  // from the in-card dropdown. `effectiveClientId` is what every call uses.
  const [selectedClientId, setSelectedClientId] = useState<string>(clientId ?? "");
  const effectiveClientId = clientId || selectedClientId || null;

  // Editable transcript (seeded from the /note prop, recording, or typed input).
  const [transcriptText, setTranscriptText] = useState(transcript ?? "");
  // MinIO key for the recording, returned by /transcribe; linked on commit.
  const [audioKey, setAudioKey] = useState<string | null>(audioKeyProp ?? null);

  // Draft data stored separately so it survives the status transition to "committing"
  const [draftData, setDraftData] = useState<NoteStructureResponse | null>(null);

  // Editable note fields (initialised from LLM draft)
  const [noteDate, setNoteDate] = useState("");
  const [noteMedium, setNoteMedium] = useState("VoiceNote");
  const [noteContact, setNoteContact] = useState("");
  const [noteBody, setNoteBody] = useState("");

  // Checked state per proposal index
  const [checkedDna, setCheckedDna] = useState<boolean[]>([]);
  const [checkedTasks, setCheckedTasks] = useState<boolean[]>([]);
  const [checkedEvents, setCheckedEvents] = useState<boolean[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const recorder = useAudioRecorder();

  async function handleStartRecording() {
    await recorder.start();
  }

  async function handleStopRecording() {
    const blob = await recorder.stop();
    if (!blob) return;
    setStatus({ kind: "transcribing" });
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      // With a client we store the clip (and link its key); without one yet we
      // transcribe-only and the RM picks the client in review.
      let text: string;
      if (effectiveClientId) {
        const res = await postTranscribe(effectiveClientId, blob, filenameForBlob(blob), ctrl.signal);
        text = res.transcript;
        setAudioKey(res.audio_key);  // links the most recent clip
      } else {
        text = await transcribeDictation(blob, filenameForBlob(blob), ctrl.signal);
      }
      // Append, so recording again from the review screen adds to the text the
      // RM is editing rather than discarding it.
      setTranscriptText((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
      setStatus({ kind: "review" });
    } catch (err: unknown) {
      if ((err as Error)?.name === "AbortError") return;
      setStatus({
        kind: "error",
        message: (err as Error).message ?? "Transcription failed",
      });
    }
  }

  async function handleStructure() {
    if (!effectiveClientId) return;
    const text = transcriptText.trim();
    if (!text) return;

    setStatus({ kind: "structuring" });
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const data = await postNoteStructure(effectiveClientId, text, todayIso(), ctrl.signal);
      setNoteDate(data.note.date ?? "");
      setNoteMedium(data.note.medium || "VoiceNote");
      setNoteContact(data.note.client_contact ?? "");
      setNoteBody(data.note.body);
      setCheckedDna(data.proposed_dna.map(() => true));
      setCheckedTasks(data.proposed_tasks.map(() => true));
      setCheckedEvents((data.proposed_events ?? []).map(() => true));
      setDraftData(data);
      setStatus({ kind: "draft" });
    } catch (err: unknown) {
      if ((err as Error)?.name === "AbortError") return;
      setStatus({
        kind: "error",
        message: (err as Error).message ?? "Failed to structure note",
      });
    }
  }

  // Clean up any in-flight request on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  async function handleApprove(
    dnaProposals: DNAProposal[],
    taskProposals: TaskProposal[],
    eventProposals: EventProposal[],
  ) {
    if (!effectiveClientId) return;
    setStatus({ kind: "committing" });

    const categories = ["values", "exclusions", "tilts", "life_events", "promises"] as const;
    const dnaDelta = Object.fromEntries(
      categories.map((cat) => [
        cat,
        dnaProposals
          .filter((d, i) => checkedDna[i] && d.category === cat)
          .map((d) => ({ text: d.text, tag: d.tag, confidence: d.confidence })),
      ]),
    ) as {
      values: object[];
      exclusions: object[];
      tilts: object[];
      life_events: object[];
      promises: object[];
    };

    const selectedEvents = eventProposals
      .filter((_, i) => checkedEvents[i])
      .map((e) => ({ title: e.title, start: e.start, end: e.end, notes: e.notes }));

    try {
      await postNoteCommit(effectiveClientId, {
        note: {
          date: noteDate || null,
          medium: noteMedium || "VoiceNote",
          rm_name: null,
          client_contact: noteContact || null,
          body: noteBody,
        },
        dna_delta: dnaDelta,
        audio_key: audioKey,
        events: selectedEvents,
      });

      const selectedTasks = taskProposals.filter((_, i) => checkedTasks[i]);
      await Promise.all(
        selectedTasks.map((t) =>
          createTask(effectiveClientId, {
            title: t.title,
            source: "note",
            execution_mode: t.execution_mode,
          }),
        ),
      );

      setStatus({ kind: "done", taskCount: selectedTasks.length });
    } catch (err: unknown) {
      setStatus({ kind: "error", message: (err as Error).message ?? "Commit failed" });
    }
  }

  // -----------------------------------------------------------------------
  // Render — early states
  // -----------------------------------------------------------------------

  if (status.kind === "no-client") {
    return (
      <div className="rounded-2xl border border-border bg-panel p-4">
        <p className="text-[13px] text-muted">
          Select a client first with{" "}
          <code className="rounded bg-panel3 px-1 py-0.5 text-[12px] text-text">/client &lt;name&gt;</code>
          , then use{" "}
          <code className="rounded bg-panel3 px-1 py-0.5 text-[12px] text-text">/note</code>.
        </p>
      </div>
    );
  }

  if (status.kind === "capture") {
    return (
      <div className="rounded-2xl border border-border bg-panel p-4 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[15px] font-semibold text-text">New voice note</p>
          <span className="rounded border border-border px-2 py-0.5 text-[11px] text-muted">
            Record or type
          </span>
        </div>

        {/* Record control */}
        <div className="flex items-center gap-3">
          {recorder.recording ? (
            <button
              type="button"
              onClick={handleStopRecording}
              className="flex items-center gap-2 rounded-lg bg-red px-4 py-1.5 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
            >
              <span className="inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-white" />
              Stop & transcribe
            </button>
          ) : (
            <button
              type="button"
              disabled={!recorder.supported}
              onClick={handleStartRecording}
              title={recorder.supported ? "Start recording" : "Recording not supported in this browser"}
              className="flex items-center gap-2 rounded-lg bg-blue px-4 py-1.5 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              🎙 Record
            </button>
          )}
          <span className="text-[12px] text-dim">
            {recorder.recording ? "Listening…" : "Whisper transcribes on stop"}
          </span>
        </div>

        {recorder.error && <p className="text-[12px] text-red">{recorder.error}</p>}

        {/* Manual fallback: type the transcript directly */}
        <div className="border-t border-border pt-3">
          <label className="block text-[11px] text-dim uppercase tracking-wider mb-1">
            …or type the note
          </label>
          <textarea
            rows={3}
            value={transcriptText}
            onChange={(e) => setTranscriptText(e.target.value)}
            disabled={recorder.recording}
            placeholder="Type what happened in the interaction…"
            className="w-full rounded-lg border border-border bg-panel2 px-2 py-1.5 text-[13px] text-text leading-relaxed resize-y placeholder:text-dim focus:outline-none focus:ring-1 focus:ring-blue/40 disabled:opacity-50"
          />
          <button
            type="button"
            disabled={!transcriptText.trim() || recorder.recording}
            onClick={handleStructure}
            className="mt-2 rounded-lg border border-border px-3 py-1.5 text-[13px] text-muted transition-colors hover:border-blue hover:text-text disabled:opacity-40"
          >
            Structure note →
          </button>
        </div>
      </div>
    );
  }

  if (status.kind === "transcribing") {
    return (
      <div className="rounded-2xl border border-border bg-panel p-4 space-y-3">
        <p className="text-[13px] text-muted animate-pulse">Transcribing audio…</p>
        <div className="h-4 w-56 animate-pulse rounded bg-panel3" />
        <div className="h-4 w-40 animate-pulse rounded bg-panel3" />
      </div>
    );
  }

  if (status.kind === "review") {
    return (
      <div className="rounded-2xl border border-border bg-panel p-4 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[15px] font-semibold text-text">Transcript</p>
          <span className="rounded border border-border px-2 py-0.5 text-[11px] text-muted">
            Edit before structuring
          </span>
        </div>
        <textarea
          rows={5}
          value={transcriptText}
          onChange={(e) => setTranscriptText(e.target.value)}
          placeholder="Transcript…"
          className="w-full rounded-lg border border-border bg-panel2 px-2 py-1.5 text-[13px] text-text leading-relaxed resize-y placeholder:text-dim focus:outline-none focus:ring-1 focus:ring-blue/40"
        />
        {/* Client picker — shown only when no client was in focus at record time. */}
        {!clientId && (
          <div>
            <label className="block text-[11px] text-dim uppercase tracking-wider mb-1">
              Client for this note
            </label>
            <select
              value={selectedClientId}
              onChange={(e) => setSelectedClientId(e.target.value)}
              className="w-full rounded-lg border border-border bg-panel2 px-2 py-1.5 text-[13px] text-text focus:outline-none focus:ring-1 focus:ring-blue/40"
            >
              <option value="">Select a client…</option>
              {(clients ?? []).map((c) => (
                <option key={c.client_id} value={c.client_id}>
                  {c.client_name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!transcriptText.trim() || !effectiveClientId || recorder.recording}
            onClick={handleStructure}
            title={!effectiveClientId ? "Pick a client first" : undefined}
            className="rounded-lg bg-blue px-4 py-1.5 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            Structure note
          </button>
          {recorder.recording ? (
            <button
              type="button"
              onClick={handleStopRecording}
              className="flex items-center gap-2 rounded-lg bg-red px-4 py-1.5 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
            >
              <span className="inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-white" />
              Stop & add
            </button>
          ) : (
            <button
              type="button"
              disabled={!recorder.supported}
              onClick={handleStartRecording}
              title={recorder.supported ? "Record more and append to the transcript" : "Recording not supported"}
              className="flex items-center gap-2 rounded-lg border border-border px-4 py-1.5 text-[13px] text-muted transition-colors hover:border-blue hover:text-text disabled:opacity-40"
            >
              🎙 Record more
            </button>
          )}
          <button
            type="button"
            disabled={recorder.recording}
            onClick={() => {
              setAudioKey(null);
              setTranscriptText("");
              setStatus({ kind: "capture" });
            }}
            className="rounded-lg border border-border px-4 py-1.5 text-[13px] text-muted transition-colors hover:text-text disabled:opacity-40"
          >
            Clear
          </button>
        </div>
        {recorder.error && <p className="text-[12px] text-red">{recorder.error}</p>}
      </div>
    );
  }

  if (status.kind === "structuring") {
    return (
      <div className="rounded-2xl border border-border bg-panel p-4 space-y-3">
        <p className="text-[13px] text-muted animate-pulse">Structuring note…</p>
        <div className="h-4 w-48 animate-pulse rounded bg-panel3" />
        <div className="h-4 w-64 animate-pulse rounded bg-panel3" />
        <div className="h-12 w-full animate-pulse rounded bg-panel3" />
      </div>
    );
  }

  if (status.kind === "done") {
    return (
      <div className="rounded-2xl border border-green/20 bg-green/5 p-4">
        <p className="text-[13px] text-green font-medium">
          Note saved.{status.taskCount > 0 ? ` ${status.taskCount} task(s) created.` : ""}
        </p>
      </div>
    );
  }

  if (status.kind === "error") {
    return (
      <div className="rounded-2xl border border-red/20 bg-red/5 p-4 space-y-2">
        <p className="text-[13px] text-red">{status.message}</p>
        <button
          type="button"
          onClick={() => {
            setDraftData(null);
            // Back to whichever step we can resume from: the transcript if we have
            // one, else the capture step.
            setStatus({ kind: transcriptText.trim() ? "review" : "capture" });
          }}
          className="text-[12px] text-muted underline hover:text-text transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Draft / committing state — main review UI
  // At this point status.kind is "draft" | "committing" and draftData is non-null
  // -----------------------------------------------------------------------

  if (!draftData) return null;

  const isCommitting = status.kind === "committing";
  const canCommit = noteBody.trim().length > 0 && !isCommitting;

  return (
    <div className="rounded-2xl border border-border bg-panel p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-[15px] font-semibold text-text">Note draft</p>
        <span className="rounded border border-border px-2 py-0.5 text-[11px] text-muted">
          Review before saving
        </span>
      </div>

      {/* Note fields */}
      <div className="space-y-2">
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="block text-[11px] text-dim uppercase tracking-wider mb-0.5">
              Date
            </label>
            <input
              type="date"
              value={noteDate}
              onChange={(e) => setNoteDate(e.target.value)}
              disabled={isCommitting}
              className="w-full rounded-lg border border-border bg-panel2 px-2 py-1.5 text-[13px] text-text focus:outline-none focus:ring-1 focus:ring-blue/40 disabled:opacity-50"
            />
          </div>
          <div className="flex-1">
            <label className="block text-[11px] text-dim uppercase tracking-wider mb-0.5">
              Medium
            </label>
            <input
              type="text"
              value={noteMedium}
              onChange={(e) => setNoteMedium(e.target.value)}
              disabled={isCommitting}
              className="w-full rounded-lg border border-border bg-panel2 px-2 py-1.5 text-[13px] text-text focus:outline-none focus:ring-1 focus:ring-blue/40 disabled:opacity-50"
            />
          </div>
          <div className="flex-1">
            <label className="block text-[11px] text-dim uppercase tracking-wider mb-0.5">
              Contact
            </label>
            <input
              type="text"
              value={noteContact}
              onChange={(e) => setNoteContact(e.target.value)}
              disabled={isCommitting}
              placeholder="—"
              className="w-full rounded-lg border border-border bg-panel2 px-2 py-1.5 text-[13px] text-text placeholder:text-dim focus:outline-none focus:ring-1 focus:ring-blue/40 disabled:opacity-50"
            />
          </div>
        </div>
        <div>
          <label className="block text-[11px] text-dim uppercase tracking-wider mb-0.5">
            Note body
          </label>
          <textarea
            rows={4}
            value={noteBody}
            onChange={(e) => setNoteBody(e.target.value)}
            disabled={isCommitting}
            className="w-full rounded-lg border border-border bg-panel2 px-2 py-1.5 text-[13px] text-text leading-relaxed resize-y focus:outline-none focus:ring-1 focus:ring-blue/40 disabled:opacity-50"
          />
        </div>
      </div>

      {/* DNA proposals */}
      {draftData.proposed_dna.length > 0 && (
        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-[11px] font-semibold text-dim uppercase tracking-wider">
            Proposed DNA updates
          </p>
          {draftData.proposed_dna.map((item: DNAProposal, i: number) => {
            const style = DNA_CATEGORY_STYLE[item.category] ?? {
              label: item.category,
              cls: "bg-panel3 text-muted border-border",
            };
            return (
              <label key={i} className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={checkedDna[i] ?? true}
                  onChange={(e) =>
                    setCheckedDna((prev) => {
                      const next = [...prev];
                      next[i] = e.target.checked;
                      return next;
                    })
                  }
                  disabled={isCommitting}
                  className="mt-0.5 accent-blue"
                />
                <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${style.cls}`}>
                  {style.label}
                </span>
                <span className="text-[13px] text-text leading-snug flex-1">{item.text}</span>
                {item.tag && (
                  <span className="shrink-0 rounded bg-panel3 border border-border px-1.5 py-0.5 text-[10px] text-muted font-mono">
                    {item.tag}
                  </span>
                )}
                <span className="shrink-0 text-[11px] text-dim">
                  {Math.round(item.confidence * 100)}%
                </span>
              </label>
            );
          })}
        </div>
      )}

      {/* Task proposals */}
      {draftData.proposed_tasks.length > 0 && (
        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-[11px] font-semibold text-dim uppercase tracking-wider">
            Proposed tasks
          </p>
          {draftData.proposed_tasks.map((task: TaskProposal, i: number) => (
            <label key={i} className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={checkedTasks[i] ?? true}
                onChange={(e) =>
                  setCheckedTasks((prev) => {
                    const next = [...prev];
                    next[i] = e.target.checked;
                    return next;
                  })
                }
                disabled={isCommitting}
                className="accent-blue"
              />
              <span className="text-[13px] text-text flex-1 leading-snug">{task.title}</span>
              <span
                className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${
                  task.execution_mode === "Auto"
                    ? "bg-violet/10 text-violet border-violet/20"
                    : "bg-panel3 text-muted border-border"
                }`}
              >
                {task.execution_mode}
              </span>
            </label>
          ))}
        </div>
      )}

      {/* Scheduled event proposals → Outlook calendar + confirmation email */}
      {(draftData.proposed_events?.length ?? 0) > 0 && (
        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-[11px] font-semibold text-dim uppercase tracking-wider">
            Proposed calendar events
          </p>
          {(draftData.proposed_events ?? []).map((event: EventProposal, i: number) => (
            <label key={i} className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={checkedEvents[i] ?? true}
                onChange={(e) =>
                  setCheckedEvents((prev) => {
                    const next = [...prev];
                    next[i] = e.target.checked;
                    return next;
                  })
                }
                disabled={isCommitting}
                className="mt-0.5 accent-blue"
              />
              <span className="flex-1 min-w-0">
                <span className="block text-[13px] text-text leading-snug font-medium">
                  {event.title}
                </span>
                <span className="block text-[11px] text-muted mt-0.5">
                  {new Date(event.start).toLocaleString()}
                </span>
                {event.notes && (
                  <span className="block text-[11px] text-dim italic mt-0.5">{event.notes}</span>
                )}
              </span>
              <span className="shrink-0 rounded border border-violet/20 bg-violet/10 text-violet px-1.5 py-0.5 text-[10px] font-medium">
                Calendar
              </span>
            </label>
          ))}
          <p className="text-[10px] text-dim">
            Saved to the Outlook calendar with an email confirmation when you commit.
          </p>
        </div>
      )}

      {/* Action row */}
      <div className="flex gap-2 border-t border-border pt-3">
        <button
          type="button"
          disabled={!canCommit}
          onClick={() =>
            handleApprove(
              draftData.proposed_dna,
              draftData.proposed_tasks,
              draftData.proposed_events ?? [],
            )
          }
          className="rounded-lg bg-blue px-4 py-1.5 text-[13px] font-medium text-white transition-opacity disabled:opacity-40 hover:opacity-90"
        >
          {isCommitting ? "Saving…" : "Approve & Commit"}
        </button>
        <button
          type="button"
          disabled={isCommitting}
          onClick={() => {
            abortRef.current?.abort();
            setDraftData(null);
            setNoteBody("");
            // Keep the transcript so the RM can tweak and re-structure.
            setStatus({ kind: "review" });
          }}
          className="rounded-lg border border-border px-4 py-1.5 text-[13px] text-muted hover:text-text transition-colors disabled:opacity-40"
        >
          Discard
        </button>
      </div>
    </div>
  );
}
