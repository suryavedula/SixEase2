# EPIC-01: Infrastructure & scaffolding [EPIC]

**Status:** BACKLOG · **Priority:** P0 · **Type:** epic · **Created:** 2026-06-20

## Goal
Stand up the local, Dockerised stack (FastAPI + React/Tailwind + Postgres/pgvector + Redis + MinIO) so all later work has a running skeleton.

## Business value
Everything runs locally with one `docker compose up`; no Azure; reproducible dev env.

## Sub-tasks
- [ ] TASK-001: Docker Compose base (postgres+pgvector, redis, minio, pgadmin, mailhog)
- [ ] TASK-002: FastAPI backend skeleton (health, settings, structure)
- [ ] TASK-003: React + Vite + Tailwind frontend skeleton (app shell + dark/light theme)
- [ ] TASK-004: Postgres schema & Alembic migrations (entities §18.1) + pgvector
- [ ] TASK-005: Redis + MinIO client wiring (cache/queue + object store)
- [ ] TASK-006: Config & secrets (.env, settings, provider base URLs)

## Refs
docs/Requirements.md · Project-Overview.html (Architecture)
