# Wealth Advisory Workbench — FastAPI backend (TASK-002, EPIC-01)
# Dev-oriented image: code is bind-mounted by compose and uvicorn runs with
# --reload, so a rebuild is only needed when requirements.txt changes.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first so the layer is cached across code edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code is bind-mounted in dev (see docker-compose). Copy it in too so the image
# is runnable standalone (e.g. without the mount).
COPY . .

EXPOSE 8000

# Entrypoint runs `alembic upgrade head` then uvicorn (TASK-004). Invoked via
# `sh` so it works regardless of the script's exec bit under the dev bind-mount.
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
