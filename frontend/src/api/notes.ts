import { API_BASE_URL, apiPost } from "./client";

export interface StructuredNote {
  date: string | null;
  medium: string;
  client_contact: string | null;
  body: string;
}

export interface DNAProposal {
  category: "values" | "exclusions" | "tilts" | "life_events" | "promises";
  text: string;
  tag: string | null;
  confidence: number;
}

export interface TaskProposal {
  title: string;
  kind: string;
  execution_mode: "Auto" | "Manual";
}

export interface EventProposal {
  title: string;
  start: string;        // local ISO-8601 datetime
  end: string | null;   // backend fills to start + 1h when absent
  notes: string | null;
}

export interface NoteStructureResponse {
  note: StructuredNote;
  proposed_dna: DNAProposal[];
  proposed_tasks: TaskProposal[];
  proposed_events?: EventProposal[];
}

export interface CommitNoteRequest {
  note: {
    date: string | null;
    medium: string;
    rm_name: null;
    client_contact: string | null;
    body: string;
  };
  dna_delta: {
    values: object[];
    exclusions: object[];
    tilts: object[];
    life_events: object[];
    promises: object[];
  };
  audio_key: string | null;
  events?: {
    title: string;
    start: string;
    end: string | null;
    notes: string | null;
  }[];
}

export interface CommitNoteResponse {
  interaction_id: string;
  dna_version: number | null;
  audio_key: string | null;
}

export interface TranscribeResponse {
  transcript: string;
  audio_key: string;
}

export function postNoteStructure(
  clientId: string,
  transcript: string,
  today: string,
  signal?: AbortSignal,
): Promise<NoteStructureResponse> {
  return apiPost<NoteStructureResponse>(
    `/clients/${clientId}/voice-notes/structure`,
    { transcript, today },
    signal,
  );
}

// Upload a recorded clip → backend stores it (MinIO) and transcribes via Whisper.
// Multipart, so it bypasses the JSON apiPost helper.
export async function postTranscribe(
  clientId: string,
  audio: Blob,
  filename = "recording.webm",
  signal?: AbortSignal,
): Promise<TranscribeResponse> {
  const form = new FormData();
  form.append("file", audio, filename);
  const res = await fetch(
    `${API_BASE_URL}/clients/${clientId}/voice-notes/transcribe`,
    { method: "POST", body: form, signal },
  );
  if (!res.ok) {
    throw new Error(
      `Transcription failed (${res.status} ${res.statusText})`,
    );
  }
  return (await res.json()) as TranscribeResponse;
}

// Client-agnostic transcription (no storage) — used when recording a note before
// a client has been chosen. The client is picked in the note card afterwards.
export async function transcribeDictation(
  audio: Blob,
  filename = "dictation.webm",
  signal?: AbortSignal,
): Promise<string> {
  const form = new FormData();
  form.append("file", audio, filename);
  const res = await fetch(`${API_BASE_URL}/voice/transcribe`, {
    method: "POST",
    body: form,
    signal,
  });
  if (!res.ok) {
    throw new Error(`Transcription failed (${res.status} ${res.statusText})`);
  }
  const data = (await res.json()) as { transcript: string };
  return data.transcript;
}

export function postNoteCommit(
  clientId: string,
  body: CommitNoteRequest,
  signal?: AbortSignal,
): Promise<CommitNoteResponse> {
  return apiPost<CommitNoteResponse>(
    `/clients/${clientId}/voice-notes/commit`,
    body,
    signal,
  );
}
