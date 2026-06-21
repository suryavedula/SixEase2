import { useCallback, useEffect, useRef, useState } from "react";

// Microphone capture for voice notes (TASK-047). Records real audio via
// MediaRecorder and hands back a Blob, which the caller uploads to the backend
// for Whisper transcription (on Phoeniqs) — unlike the conversational dictation
// mic (useVoiceInput), which uses the browser's cloud Web Speech API.

interface UseAudioRecorderReturn {
  supported: boolean;
  recording: boolean;
  error: string | null;
  start: () => Promise<void>;
  /** Stops recording and resolves with the captured audio Blob (null if nothing recorded). */
  stop: () => Promise<Blob | null>;
  reset: () => void;
}

// Prefer formats Whisper accepts; the browser falls back to its default if none match.
const PREFERRED_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return PREFERRED_MIME_TYPES.find((t) => MediaRecorder.isTypeSupported(t));
}

export function useAudioRecorder(): UseAudioRecorderReturn {
  const supported =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined";

  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  // Stop the mic if the component unmounts mid-recording.
  useEffect(() => cleanupStream, [cleanupStream]);

  const start = useCallback(async () => {
    if (!supported || recording) return;
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorderRef.current = recorder;
      // Timeslice → periodic dataavailable so chunks flush even on a short clip.
      recorder.start(250);
      setRecording(true);
    } catch (err) {
      cleanupStream();
      const name = (err as Error)?.name;
      setError(
        name === "NotAllowedError"
          ? "Microphone access denied. Allow it in your browser to record."
          : "Could not start recording. Check your microphone.",
      );
    }
  }, [supported, recording, cleanupStream]);

  const stop = useCallback((): Promise<Blob | null> => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      setRecording(false);
      cleanupStream();
      return Promise.resolve(null);
    }
    return new Promise<Blob | null>((resolve) => {
      recorder.onstop = () => {
        const type = recorder.mimeType || "audio/webm";
        const blob = chunksRef.current.length
          ? new Blob(chunksRef.current, { type })
          : null;
        chunksRef.current = [];
        setRecording(false);
        cleanupStream();
        resolve(blob);
      };
      recorder.stop();
    });
  }, [cleanupStream]);

  const reset = useCallback(() => {
    chunksRef.current = [];
    setError(null);
  }, []);

  return { supported, recording, error, start, stop, reset };
}
