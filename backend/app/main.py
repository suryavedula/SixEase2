"""FastAPI application entrypoint (TASK-002, EPIC-01).

Wires settings, structured logging, CORS, and the routers package. Domain
routers (DNA, portfolio, alerts, messages, generative UI) are mounted here by
their owning tasks; this skeleton ships only the health probes.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.llm import close_llm, ping_llm
from app.news import close_news, ping_news
from app.loaders.news_fanout import start_fanout, stop_fanout
from app.poller import start_poller, stop_poller
from app.six import close_six, ping_six
from app.logging import configure_logging, get_logger
from app.redis_client import close_redis, ping_redis
from app.routers import admin, alerts, book, dna, health, messages, orchestrate, portfolio, similarity, tasks, voice_writeback, watchlist
from app.storage import ensure_bucket

settings = get_settings()
configure_logging(log_level=settings.log_level, environment=settings.environment)
log = get_logger(__name__)

_poller_task: asyncio.Task[None] | None = None
_fanout_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "app.startup",
        service=settings.app_name,
        environment=settings.environment,
        database=f"{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}",
        llm_provider=settings.llm.provider,
        llm_model=settings.llm.model,
    )

    # Provider secrets are optional at boot: a missing key degrades one feature
    # but must never crash the app (TASK-006 acceptance criterion). Log each so
    # the operator knows what runs degraded until the key is supplied.
    for secret in settings.missing_secrets():
        log.warning("startup.missing_secret", key=secret.key, disables=secret.feature)

    # Bootstrap object storage (idempotent) and confirm Redis connectivity.
    # Failures are logged but non-fatal — the readiness probe reports degraded
    # state rather than blocking process startup.
    try:
        ensure_bucket()
    except Exception as exc:  # noqa: BLE001 — startup must not crash on infra hiccup
        log.warning("startup.minio_unavailable", error=str(exc))
    try:
        await ping_redis()
        log.info("startup.redis_ok", redis=f"{settings.redis_host}:{settings.redis_port}")
    except Exception as exc:  # noqa: BLE001
        log.warning("startup.redis_unavailable", error=str(exc))

    try:
        await ping_llm()
        log.info("startup.llm_ok", provider=settings.llm.provider, model=settings.llm.model)
    except Exception as exc:  # noqa: BLE001
        log.warning("startup.llm_unavailable", error=str(exc))

    try:
        await ping_six()
        log.info("startup.six_ok", url=settings.six_mcp_url)
    except Exception as exc:  # noqa: BLE001
        log.warning("startup.six_unavailable", error=str(exc))

    try:
        await ping_news()
        log.info("startup.news_ok", url=settings.newsai_api_url)
    except Exception as exc:  # noqa: BLE001
        log.warning("startup.news_unavailable", error=str(exc))

    global _poller_task, _fanout_task
    _poller_task = start_poller()
    _fanout_task = start_fanout()

    yield

    if _fanout_task:
        await stop_fanout(_fanout_task)
    if _poller_task:
        await stop_poller(_poller_task)
    await close_redis()
    await close_llm()
    await close_six()
    await close_news()
    log.info("app.shutdown")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers — domain routers are appended by later tasks.
app.include_router(health.router)
app.include_router(admin.router)
app.include_router(similarity.router)
app.include_router(dna.router)
app.include_router(portfolio.router)
app.include_router(alerts.router)
app.include_router(book.router)
app.include_router(watchlist.router)
app.include_router(messages.router)
app.include_router(tasks.router)
app.include_router(voice_writeback.router)
app.include_router(orchestrate.router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs", "health": "/health"}
