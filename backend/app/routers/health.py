"""Health & readiness probes (TASK-002, EPIC-01).

- `GET /health`  — liveness: always cheap, no external deps. Used by the compose
  healthcheck and load balancers (satisfies the TASK-002 acceptance criterion).
- `GET /health/ready` — readiness: also pings Postgres so orchestration can wait
  for real dependency availability, not just process liveness.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import ping_db
from app.logging import get_logger
from app.redis_client import ping_redis
from app.storage import ping_storage

router = APIRouter(tags=["health"])
log = get_logger(__name__)
settings = get_settings()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    checks: dict[str, str] = {}
    healthy = True

    try:
        await ping_db()
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 — probe must report, not raise
        healthy = False
        checks["postgres"] = "unavailable"
        log.warning("readiness.postgres_unavailable", error=str(exc))

    try:
        await ping_redis()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        healthy = False
        checks["redis"] = "unavailable"
        log.warning("readiness.redis_unavailable", error=str(exc))

    try:
        ping_storage()
        checks["minio"] = "ok"
    except Exception as exc:  # noqa: BLE001
        healthy = False
        checks["minio"] = "unavailable"
        log.warning("readiness.minio_unavailable", error=str(exc))

    status = "ok" if healthy else "degraded"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": status, "checks": checks},
    )
