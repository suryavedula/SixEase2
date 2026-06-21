"""Application settings (TASK-002, EPIC-01).

All configuration is loaded from the environment (the root `.env` is passed to the
container via `env_file` in docker-compose). Field names mirror the keys already
defined in `.env.example` so the same file drives both the data stack and the app.

Later tasks extend this model in place: provider keys (TASK-006/012/013/014),
MinIO/object-store config (TASK-005), etc.
"""

from dataclasses import dataclass
from functools import lru_cache

from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Providers whose LLM backend is hosted (need an API key); Ollama is local and
# keyless. Used by both `Settings.llm` resolution and `missing_secrets()`.
_KNOWN_LLM_PROVIDERS = ("ollama", "openrouter", "phoeniqs")


@dataclass(frozen=True)
class LLMConfig:
    """A resolved, OpenAI-compatible LLM backend (ST1 provider abstraction).

    The three providers (Ollama / OpenRouter / Phoeniqs) are interchangeable by
    config; TASK-012 builds one client from `base_url` + `api_key` + `model`.
    `api_key` is empty for the keyless local Ollama path.
    """

    provider: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class MissingSecret:
    """A provider key that is unset and the capability it gates.

    Surfaced at startup as a warning (never an exception) so the operator knows
    which feature runs degraded — see `Settings.missing_secrets`.
    """

    key: str
    feature: str


class Settings(BaseSettings):
    # `extra="ignore"` so the shared .env (which also holds compose-only and
    # later-task keys) doesn't fail validation here.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---------------------------------------------------------------
    app_name: str = "SixEase — Wealth Advisor Workbench API"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    # Comma-separated origins; the Vite dev server (TASK-003) defaults to 5173.
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:3000")

    # --- Postgres (+pgvector) ---------------------------------------------
    # Host defaults to the compose service name; override to localhost when
    # running the app outside the compose network.
    #
    # NB: the *container* port (below) is deliberately NOT bound to the shared
    # `POSTGRES_PORT` env var — that one is the host-published port (often
    # remapped, e.g. 15432, to avoid local collisions). Inside the compose
    # network Postgres always listens on 5432. Override via the dedicated
    # `POSTGRES_CONTAINER_PORT` only when connecting from outside compose.
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(
        default=5432, validation_alias=AliasChoices("POSTGRES_CONTAINER_PORT")
    )
    postgres_user: str = Field(default="wealth")
    postgres_password: str = Field(default="wealth")
    postgres_db: str = Field(default="wealth")

    # --- Redis -------------------------------------------------------------
    # Same host- vs. container-port distinction as Postgres (see note above).
    redis_host: str = Field(default="redis")
    redis_port: int = Field(
        default=6379, validation_alias=AliasChoices("REDIS_CONTAINER_PORT")
    )

    # --- MinIO (S3-compatible object store) — TASK-005 --------------------
    # Same host- vs. container-port distinction as Postgres/Redis: the app
    # talks to `minio:9000` *inside* the compose network, not the host-published
    # `MINIO_API_PORT`. Override the container port via `MINIO_CONTAINER_PORT`
    # only when connecting from outside compose. `minio_secure=False` because
    # local MinIO serves plain HTTP.
    minio_host: str = Field(default="minio")
    minio_port: int = Field(
        default=9000, validation_alias=AliasChoices("MINIO_CONTAINER_PORT")
    )
    minio_root_user: str = Field(default="minioadmin")
    minio_root_password: str = Field(default="minioadmin")
    minio_bucket: str = Field(default="wealth")
    minio_secure: bool = Field(default=False)

    # --- MailHog SMTP (dev email handoff testing, MSG9 / TASK-039) -------
    # Same host-vs-container-port distinction as Postgres/Redis/MinIO: the app
    # talks to mailhog:1025 inside compose; host-published port is MAILHOG_SMTP_PORT.
    # mailhog_ui_port is the host-published web UI port (for the send-test response URL).
    mailhog_host: str = Field(default="mailhog")
    mailhog_smtp_port: int = Field(
        default=1025, validation_alias=AliasChoices("MAILHOG_CONTAINER_SMTP_PORT")
    )
    mailhog_ui_port: int = Field(
        default=8025, validation_alias=AliasChoices("MAILHOG_UI_PORT")
    )

    # --- Workbook data directory (TASK-008/009 loaders) ------------------
    # Overridable so loaders work both inside the container (/app/data, the
    # compose bind-mount default) and on the host (point at the repo data/).
    wealth_data_dir: str = Field(default="/app/data")

    # --- Embeddings (TASK-004 schema; consumed by TASK-015) ---------------
    # Dimension of the pgvector `embeddings.vector` column. Default 768 matches
    # `nomic-embed-text` (the planned Ollama embedding model). MUST agree with
    # whatever model TASK-015 wires up; changing it is a one-line new migration.
    embed_dim: int = Field(default=768)

    # --- LLM provider abstraction (§20 ST1) — TASK-006 / consumed by 012 ---
    # One OpenAI-compatible interface; switch backend by `LLM_PROVIDER`:
    #   ollama     — local Gemma 3 12B, fully private (production/privacy path)
    #   openrouter — hosted open-source, for VRAM-limited dev/demo
    #   phoeniqs   — provided credits / fallback
    # Each backend keeps its own base URL / key / model so switching is config-
    # only. The resolved triple is exposed via the `llm` property (below).
    llm_provider: str = Field(default="ollama")

    ollama_base_url: str = Field(default="http://ollama:11434/v1")
    ollama_model: str = Field(default="gemma3:12b")
    # Embedding model served by Ollama (TASK-015). Its output dimension MUST
    # match `embed_dim` above (nomic-embed-text → 768).
    ollama_embed_model: str = Field(default="nomic-embed-text")

    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")
    openrouter_api_key: str = Field(default="")
    openrouter_model: str = Field(default="google/gemma-3-12b-it")

    phoeniqs_api_url: str = Field(default="https://maas.phoeniqs.com/v1")
    phoeniqs_api_key: str = Field(default="")
    phoeniqs_model: str = Field(default="inference-gpt-oss-120b")

    # --- Hosted-LLM token budget guard (always-on safety) — proactive loops ---
    # Daily (UTC) total-token cap for the active *hosted* provider (Ollama is free
    # and never metered). When reached, llm.chat() raises BudgetExhausted before
    # spending; callers degrade softly (re-enqueue / skip) and the zero-LLM Change
    # Radar keeps running. `0` disables the cap. Surfaced via GET /admin/budget.
    phoeniqs_budget_tokens: int = Field(default=2_000_000)
    # Emit a one-time log warning when cumulative daily spend crosses this percent
    # of the cap. `0` disables the warning.
    phoeniqs_budget_warn_pct: int = Field(default=80)
    # --- Speech-to-text (voice notes, TASK-047 capture path) --------------
    # Whisper is decoupled from `llm_provider` (like embeddings → Ollama). Pick
    # the backend with `whisper_provider`:
    #   local    — faster-whisper-server container on the GPU (default; offline,
    #              reliable, on the no-cloud ethos). OpenAI-compatible /v1.
    #   phoeniqs — hosted Whisper on Phoeniqs (~0.006 credits/min; was GPU-OOM
    #              flaky under hackathon load).
    # Resolved into a single (base_url, key, model) triple by the `whisper`
    # property below.
    whisper_provider: str = Field(default="local")
    whisper_base_url: str = Field(default="http://whisper:8000/v1")
    whisper_model: str = Field(default="Systran/faster-whisper-large-v3")
    phoeniqs_whisper_model: str = Field(default="inference-whisper-large-v3")

    # --- SIX Financial Data (external MCP server) — TASK-006 / used by 013 -
    six_mcp_url: str = Field(
        default="https://ca-mcpwebapi-tools.nicepebble-599ed11f.westeurope.azurecontainerapps.io/mcp"
    )
    six_mcp_token: str = Field(default="")

    # --- Microsoft Graph (inbound email transport) — TASK-060 ----------------
    # SCOPED EXCEPTION to the "no Azure" rule (§20): Azure is used here ONLY as an
    # email *transport* (read-only Mail.Read via client-credentials), never as infra.
    # All four must be set for ingestion to run; otherwise it degrades to a no-op
    # (see `ms_graph_enabled` + `missing_secrets`). `ms_graph_mailbox` is the RM's
    # UPN/address — a message whose `from` equals it is outbound (context-only).
    ms_graph_tenant_id: str = Field(default="")
    ms_graph_client_id: str = Field(default="")
    ms_graph_client_secret: str = Field(default="")
    ms_graph_mailbox: str = Field(default="")
    # Graph REST + OAuth endpoints (overridable for sovereign/national clouds).
    ms_graph_authority: str = Field(default="https://login.microsoftonline.com")
    ms_graph_base_url: str = Field(default="https://graph.microsoft.com/v1.0")
    # Auth mode (TASK-061):
    #   app       → client-credentials, app-only (original TASK-060 inbound path).
    #   delegated → web "Sign in with Microsoft" (auth-code + PKCE). The RM signs
    #               in with their OWN account; the app reads/sends THROUGH the
    #               shared `ms_graph_mailbox` via Mail.Read.Shared / Mail.Send.Shared.
    ms_graph_auth_mode: str = Field(default="app")
    # Backend callback URL — must match a redirect URI on the Azure app registration.
    ms_graph_redirect_uri: str = Field(default="")
    # Delegated scopes (comma-separated). MSAL injects openid/profile/offline_access
    # itself — do NOT list those here. Calendars.ReadWrite enables note→calendar
    # write-back (TASK-062 Part B); drop it if you don't grant that permission.
    ms_graph_scopes: str = Field(default="Mail.Read.Shared,Mail.Send.Shared,Calendars.ReadWrite")
    # SPA URL the callback bounces back to after sign-in; defaults to first CORS origin.
    ms_graph_post_login_redirect: str = Field(default="")
    # Permit outbound send via Graph (RM-only — see notify.py). Off by default so the
    # default transport stays MailHog/SMTP and the G1 boundary is explicit.
    ms_graph_send_enabled: bool = Field(default=False)
    # Timezone for calendar events created from notes (IANA name).
    ms_graph_calendar_timezone: str = Field(default="Europe/Zurich")

    # --- Email auto-draft (TASK-062 Part A) ----------------------------------
    # When a NEW inbound email lands on the radar, the agent pre-drafts the answer
    # (a reply for correspondence; an advisory for a holding) for RM review — draft
    # only, never sent (G1). Off → emails still hit the radar, just no auto-draft.
    email_autodraft_enabled: bool = Field(default=True)
    # Cap drafts produced per refresh cycle (LLM-budget guard against an inbox flood).
    email_autodraft_max_per_cycle: int = Field(default=3)

    # --- News = Event Registry / newsapi.ai (REST) — TASK-006 / used by 014 -
    newsapi_key: str = Field(default="")
    newsai_api_url: str = Field(default="https://eventregistry.org/api/v1")
    news_poll_interval: int = Field(default=1800)  # seconds; 30 min — token-budget conscious (Event Registry ~5k-token cap)
    # Event Registry caps the number of keywords per query by subscription tier
    # (hackathon tier = 80). The global firehose filter is ranked by cross-client
    # breadth and truncated to this many — see watchlist.get_global_index.
    news_max_keywords: int = Field(default=80)
    # Proactive Change Radar refresh interval (seconds). A background task re-
    # materialises the radar snapshot from continuously-ingested news/alerts so the
    # RM always opens a current radar without a manual /admin/seed/radar. Pure
    # aggregation (no LLM) → zero hosted-LLM (Phoeniqs) budget. Default 5 min.
    radar_refresh_interval: int = Field(default=300)

    # --- SIX price-watch loop (proactive layer — the free, non-token-metered axis)
    # Scans held instruments via SIX (JSON-RPC, NOT token-billed → zero Phoeniqs
    # budget) and emits price_move / maturity_soon Alert rows that flow through the
    # radar like drift/news. Disabled to a no-op when off or SIX_MCP_TOKEN is unset.
    price_watch_enabled: bool = Field(default=True)
    price_watch_interval: int = Field(default=900)  # seconds; 15 min
    # Absolute % move (vs last close / session open) that triggers a price_move alert.
    price_move_threshold_pct: float = Field(default=5.0)
    # Escalate a price_move alert to CRITICAL at/above this absolute % move.
    price_move_critical_pct: float = Field(default=10.0)
    # Flag a held bond when it matures within this many days (maturity_soon alert).
    bond_maturity_horizon_days: int = Field(default=30)
    # Per-position pause in the scan loop. SIX caps at 5 req/s per cert and each
    # position makes one SIX call, so ~0.25s keeps the sequential scan under it.
    price_watch_throttle_s: float = Field(default=0.25)

    # Semantic relevance gate (EPIC-06 precision/cost): max cosine *distance*
    # (0 = identical, 1 = orthogonal) between an article's embedding and a
    # client's DNA profile vector for a care-axis / non-direct match to count.
    # A direct holding (own-axis) match bypasses this gate. Tuned so each persona
    # trigger passes while off-profile articles drop. Local Ollama embeddings, so
    # this gate spends **zero** hosted-LLM (Phoeniqs) budget.
    news_relevance_max_distance: float = Field(default=0.6)
    # Master switch for the embedding relevance gate. It needs a reachable Ollama
    # embeddings endpoint (`ollama_base_url` + `ollama_embed_model`); when that is
    # unavailable the gate self-degrades to a no-op (logged once) so it never blocks
    # news fan-out. Set false to skip it entirely (e.g. Ollama not deployed).
    news_relevance_enabled: bool = Field(default=True)

    # Cross-encoder rerank precision gate (EPIC-06 C2). A second, sharper local
    # precision stage that scores the (matched-entity, article) pair JOINTLY and
    # demotes vocabulary-overlap false positives the bi-encoder cosine gate keeps —
    # run on the shortlist, BEFORE the hosted-LLM call, so it also cuts Phoeniqs
    # spend. Fully local via fastembed/onnxruntime (no torch, no cloud). OFF by
    # default: enabling requires the optional `fastembed` dependency (see
    # requirements.txt) and downloads the model on first use. When enabled it loads
    # eagerly and raises on failure rather than silently passing matches through.
    news_cross_encoder_enabled: bool = Field(default=False)
    news_cross_encoder_model: str = Field(default="Xenova/ms-marco-MiniLM-L-6-v2")
    # ms-marco MiniLM emits logit scores (~ -11..+11); > 0 ≈ genuinely relevant.
    news_cross_encoder_min_score: float = Field(default=0.0)

    # --- Proactive radar dispatch (EPIC-08 — push, not pull) -----------------
    # Turns the pull-only radar into push: Critical changes go to the RM in near-
    # real-time (in-app SSE + email), everything else into a once-daily digest.
    # Delivery is deduped via the radar_deliveries table. RM-only — nothing here
    # reaches a client (autonomy boundary G1). No-op when disabled.
    radar_dispatch_enabled: bool = Field(default=True)
    radar_dispatch_interval: int = Field(default=60)  # seconds between dispatch cycles
    # A change is "Critical" (near-real-time push) when its aggregate event
    # magnitude (severity-band × confidence, 0..~1) is at/above this. Magnitude is
    # portfolio-independent (unlike raw impact_score, which scales with CHF), so it
    # maps cleanly to a Critical-severity underlying alert across all sources.
    radar_critical_magnitude: float = Field(default=0.9)
    # Re-notify an already-delivered change only when its impact_score climbs above
    # (1 + margin) × the impact at last delivery — avoids alert churn on small moves.
    radar_rebroadcast_margin: float = Field(default=0.5)
    radar_digest_hour: int = Field(default=7)   # local hour (0-23) to send the daily digest
    radar_digest_limit: int = Field(default=10)  # max non-critical changes in the digest
    # Quiet hours: in-app SSE still fires, but Critical *emails* are deferred to the
    # next digest. Wrap-around supported (e.g. 22→7 spans midnight). Equal = no quiet.
    radar_quiet_start: int = Field(default=22)
    radar_quiet_end: int = Field(default=7)

    # --- RM-only outbound email transport (SMTP) — proactive dispatch --------
    # The ONLY outbound-send path in the backend; targets the RM (rm_email) ONLY,
    # never a client (G1). No-op + warning when unset. Defaults suit a local MailHog
    # container (host "mailhog", port 1025, no TLS); set real SMTP for production.
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=1025)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="sixease@localhost")
    smtp_starttls: bool = Field(default=False)
    rm_email: str = Field(default="")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN (asyncpg driver)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def minio_endpoint(self) -> str:
        """`host:port` (no scheme) — the form the MinIO SDK expects."""
        return f"{self.minio_host}:{self.minio_port}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ms_graph_enabled(self) -> bool:
        """True only when every Graph credential is set (TASK-060).

        The email-ingest loader gates on this: unset → return no signals (the
        offline persona demo stays green); set-but-failing → raise loud at call time.
        """
        return bool(
            self.ms_graph_tenant_id
            and self.ms_graph_client_id
            and self.ms_graph_client_secret
            and self.ms_graph_mailbox
        )

    @property
    def ms_graph_delegated_enabled(self) -> bool:
        """True when the delegated "Sign in with Microsoft" flow can run (TASK-061).

        Needs every Graph credential (as `ms_graph_enabled`) plus a registered
        redirect URI and `ms_graph_auth_mode=delegated`. The /auth/ms/login route
        returns 503 when this is false rather than starting a broken OAuth dance.
        """
        return bool(
            self.ms_graph_enabled
            and self.ms_graph_redirect_uri
            and self.ms_graph_auth_mode.strip().lower() == "delegated"
        )

    @property
    def whisper(self) -> LLMConfig:
        """The resolved Whisper backend (TASK-047), independent of `llm_provider`.

        `local` (default) → the keyless faster-whisper-server container; `phoeniqs`
        → hosted Whisper with the Phoeniqs key. Reuses LLMConfig's
        (provider, base_url, api_key, model) shape.
        """
        if self.whisper_provider.strip().lower() == "phoeniqs":
            return LLMConfig(
                "phoeniqs", self.phoeniqs_api_url, self.phoeniqs_api_key, self.phoeniqs_whisper_model
            )
        return LLMConfig("local", self.whisper_base_url, "", self.whisper_model)

    @property
    def whisper_enabled(self) -> bool:
        """True when voice-note transcription can run (TASK-047 capture path).

        Local Whisper needs only a reachable container (no key). The hosted
        Phoeniqs backend needs its key — the transcribe endpoint surfaces a loud
        error when unset (no silent fallback).
        """
        if self.whisper_provider.strip().lower() == "phoeniqs":
            return bool(self.phoeniqs_api_key)
        return True

    @property
    def llm(self) -> LLMConfig:
        """The active LLM backend resolved from `llm_provider` (§20 ST1).

        An unknown provider falls back to the keyless local Ollama path rather
        than crashing; the misconfiguration is reported by `missing_secrets()`.
        """
        provider = self.llm_provider.strip().lower()
        backends = {
            "ollama": LLMConfig("ollama", self.ollama_base_url, "", self.ollama_model),
            "openrouter": LLMConfig(
                "openrouter", self.openrouter_base_url, self.openrouter_api_key, self.openrouter_model
            ),
            "phoeniqs": LLMConfig(
                "phoeniqs", self.phoeniqs_api_url, self.phoeniqs_api_key, self.phoeniqs_model
            ),
        }
        return backends.get(provider, backends["ollama"])

    def missing_secrets(self) -> list[MissingSecret]:
        """Provider keys that are unset, each paired with the feature it gates.

        Logged as warnings at startup (see `app.main`) — the app boots and runs
        degraded rather than failing. Only the secrets relevant to the *active*
        LLM provider are checked (the local Ollama path needs no key).
        """
        missing: list[MissingSecret] = []

        provider = self.llm_provider.strip().lower()
        if provider not in _KNOWN_LLM_PROVIDERS:
            missing.append(
                MissingSecret(
                    "LLM_PROVIDER",
                    f"unknown provider '{self.llm_provider}' — falling back to local Ollama",
                )
            )
        elif provider == "openrouter" and not self.openrouter_api_key:
            missing.append(MissingSecret("OPENROUTER_API_KEY", "LLM generation (OpenRouter selected)"))
        elif provider == "phoeniqs" and not self.phoeniqs_api_key:
            missing.append(MissingSecret("PHOENIQS_API_KEY", "LLM generation (Phoeniqs selected)"))

        if not self.whisper_enabled:
            missing.append(
                MissingSecret("PHOENIQS_API_KEY", "Voice-note transcription (Whisper on Phoeniqs)")
            )
        if not self.six_mcp_token:
            missing.append(MissingSecret("SIX_MCP_TOKEN", "SIX market data (prices, instrument lookup)"))
        if not self.newsapi_key:
            missing.append(MissingSecret("NEWSAPI_KEY", "Event Registry news + sentiment monitoring"))
        if not self.ms_graph_enabled:
            missing.append(
                MissingSecret("MS_GRAPH_*", "Email ingestion via Microsoft Graph (Change Radar email signals)")
            )

        return missing


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — import this everywhere rather than instantiating Settings."""
    return Settings()
