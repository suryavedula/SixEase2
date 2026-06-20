"""Object storage wiring — MinIO / S3 (TASK-005, EPIC-01).

Mirrors the `app/db.py` shape: one module-level client plus a `ping_*()` check
for the readiness probe. The bucket is bootstrapped idempotently from the app
lifespan (`ensure_bucket`), satisfying the "minio bucket created on startup"
acceptance criterion.

Consumed later by voice-note storage (TASK-046) and fact-sheet rendering
(TASK-037); helper signatures are generic so those tasks reuse them unchanged.

NB the `minio` SDK is **synchronous**. Bucket bootstrap at startup is fine
called directly; if a hot async request path ever needs object I/O, wrap these
calls in `asyncio.to_thread` to avoid blocking the event loop.
"""

from io import BytesIO

from minio import Minio

from app.config import get_settings
from app.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

# Module-level singleton. Endpoint is the in-network `minio:9000` (host:port,
# no scheme); `secure=False` for local plain-HTTP MinIO.
client: Minio = Minio(
    settings.minio_endpoint,
    access_key=settings.minio_root_user,
    secret_key=settings.minio_root_password,
    secure=settings.minio_secure,
)

_BUCKET = settings.minio_bucket


def ensure_bucket() -> None:
    """Create the configured bucket if absent (idempotent). Call on startup."""
    if not client.bucket_exists(_BUCKET):
        client.make_bucket(_BUCKET)
        log.info("storage.bucket_created", bucket=_BUCKET)
    else:
        log.info("storage.bucket_exists", bucket=_BUCKET)


def ping_storage() -> bool:
    """Connectivity check used by the readiness probe."""
    return client.bucket_exists(_BUCKET)


def put_object(
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> None:
    """Store `data` under `key` in the configured bucket."""
    client.put_object(
        _BUCKET,
        key,
        BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def get_object(key: str) -> bytes:
    """Fetch the object at `key` and return its bytes."""
    response = client.get_object(_BUCKET, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
