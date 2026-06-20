# Local stack (TASK-001)

Base data/dev services for the Wealth Advisory Workbench: **postgres (+pgvector) · redis ·
minio · pgadmin · mailhog**. App services (backend/frontend/ollama/mcp-proxy) are added by
later tasks — see the commented stubs in `../docker-compose.yml`.

## Run

```bash
cp .env.example .env          # adjust ports/creds if needed
docker compose up -d
docker compose ps             # all 5 services -> (healthy)
```

## Endpoints (defaults from `.env.example`)

| Service | URL / port | Credentials |
|---|---|---|
| Postgres | `localhost:5432` | `${POSTGRES_USER}` / `${POSTGRES_PASSWORD}` |
| Redis | `localhost:6379` | — |
| MinIO API | `localhost:9000` | `${MINIO_ROOT_USER}` / `${MINIO_ROOT_PASSWORD}` |
| MinIO console | http://localhost:9001 | same as API |
| pgAdmin | http://localhost:5050 | `${PGADMIN_DEFAULT_EMAIL}` / `${PGADMIN_DEFAULT_PASSWORD}` |
| MailHog UI | http://localhost:8025 | — |

## Verify pgvector

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT extname FROM pg_extension WHERE extname='vector';"   # -> vector
```

`docker compose down` stops the stack; named volumes (`pgdata`, `redisdata`, `miniodata`,
`pgadmindata`) persist data across restarts. Use `docker compose down -v` to wipe them.
