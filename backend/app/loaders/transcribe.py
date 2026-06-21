"""Voice-note speech-to-text via Whisper on Phoeniqs (TASK-047 capture path).

Turns a recorded audio clip into a raw transcript that the downstream note
structuring pipeline (`note_structure.structure_note`) extracts a CRM note, DNA
updates, and tasks from. Transcription itself does no extraction — it only
produces text for the RM to review and edit before anything is structured (G1).

Whisper ALWAYS runs on Phoeniqs (OpenAI-compatible /v1/audio/transcriptions),
independent of `llm_provider` — exactly like embeddings always run on Ollama.
A dedicated client pins it to the Phoeniqs endpoint + key so it works even when
the active LLM is local Ollama.

Public API:
    transcribe_audio(audio, filename, content_type, language) -> str
"""

from openai import AsyncOpenAI

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)
settings = get_settings()

# Pinned to Phoeniqs regardless of LLM_PROVIDER (see module docstring).
_whisper_client: AsyncOpenAI | None = None


def _get_whisper_client() -> AsyncOpenAI:
    """Lazy AsyncOpenAI singleton pinned to the resolved Whisper backend.

    Local faster-whisper-server is keyless (like Ollama); hosted Phoeniqs needs a
    key and raises loudly when unset rather than silently degrading (no-fallback).
    """
    global _whisper_client
    if _whisper_client is None:
        cfg = settings.whisper
        if cfg.provider == "phoeniqs" and not cfg.api_key:
            raise RuntimeError(
                "PHOENIQS_API_KEY is not set but WHISPER_PROVIDER=phoeniqs — "
                "set the key or switch WHISPER_PROVIDER=local, then restart."
            )
        # The openai SDK rejects an empty api_key; the local server ignores it.
        _whisper_client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key or "nokey")
        log.info("whisper.init", provider=cfg.provider, model=cfg.model, base_url=cfg.base_url)
    return _whisper_client


async def transcribe_audio(
    audio: bytes,
    *,
    filename: str = "recording.webm",
    content_type: str = "audio/webm",
    language: str | None = None,
) -> str:
    """Transcribe a recorded audio clip to text via Whisper on Phoeniqs.

    `filename` is passed through to the API (Whisper infers the container format
    from the extension); `content_type` is the recorder's MIME type. `language`
    is an optional ISO-639-1 hint (e.g. "en", "de") — omitted means auto-detect.

    Returns the raw transcript. Raises on transport/model error so the caller
    surfaces an explicit failure (no silent empty-string fallback).
    """
    client = _get_whisper_client()
    log.info(
        "whisper.transcribe.start",
        bytes=len(audio),
        filename=filename,
        content_type=content_type,
        language=language,
    )
    resp = await client.audio.transcriptions.create(
        model=settings.whisper.model,
        file=(filename, audio, content_type),
        **({"language": language} if language else {}),
    )
    text = (resp.text or "").strip()
    log.info("whisper.transcribe.done", transcript_len=len(text))
    return text
