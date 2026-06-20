import { useCallback, useEffect, useRef, useState } from "react";

interface UseVoiceInputReturn {
  supported: boolean;
  recording: boolean;
  transcript: string;
  start: () => void;
  stop: () => void;
  clear: () => void;
}

export function useVoiceInput(): UseVoiceInputReturn {
  const Ctor =
    typeof window !== "undefined"
      ? (window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null)
      : null;

  const supported = Ctor !== null;
  const [recording, setRecording] = useState(false);
  const [transcript, setTranscript] = useState("");
  const recRef = useRef<SpeechRecognition | null>(null);

  useEffect(() => {
    if (!Ctor) return;

    const rec = new Ctor();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";

    rec.onresult = (event: SpeechRecognitionEvent) => {
      let text = "";
      for (let i = 0; i < event.results.length; i++) {
        text += event.results[i][0].transcript;
      }
      setTranscript(text);
    };

    rec.onend = () => setRecording(false);

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      setRecording(false);
      if (event.error === "not-allowed") setTranscript("");
    };

    recRef.current = rec;
    return () => {
      rec.abort();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback(() => {
    if (!recRef.current || recording) return;
    setTranscript("");
    recRef.current.start();
    setRecording(true);
  }, [recording]);

  const stop = useCallback(() => {
    if (!recRef.current || !recording) return;
    recRef.current.stop();
  }, [recording]);

  const clear = useCallback(() => setTranscript(""), []);

  return { supported, recording, transcript, start, stop, clear };
}
