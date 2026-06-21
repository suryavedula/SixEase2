#!/bin/sh
# TASK-004: apply migrations, then start the app.
# compose `depends_on: postgres (service_healthy)` guarantees the DB is up here.
set -e

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] starting uvicorn"
# --timeout-graceful-shutdown bounds shutdown so a long-lived SSE connection
# (GET /radar/stream, EPIC-08) can never hang a --reload or container restart.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --timeout-graceful-shutdown 10
