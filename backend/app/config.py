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
    app_name: str = "Wealth Advisory Workbench API"
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

    # --- SIX Financial Data (external MCP server) — TASK-006 / used by 013 -
    six_mcp_url: str = Field(
        default="https://ca-mcpwebapi-tools.nicepebble-599ed11f.westeurope.azurecontainerapps.io/mcp"
    )
    six_mcp_token: str = Field(default="")

    # --- News = Event Registry / newsapi.ai (REST) — TASK-006 / used by 014 -
    newsapi_key: str = Field(default="")
    newsai_api_url: str = Field(default="https://eventregistry.org/api/v1")
    news_poll_interval: int = Field(default=300)  # seconds; 5 min per §14.3

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

        if not self.six_mcp_token:
            missing.append(MissingSecret("SIX_MCP_TOKEN", "SIX market data (prices, instrument lookup)"))
        if not self.newsapi_key:
            missing.append(MissingSecret("NEWSAPI_KEY", "Event Registry news + sentiment monitoring"))

        return missing


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — import this everywhere rather than instantiating Settings."""
    return Settings()
