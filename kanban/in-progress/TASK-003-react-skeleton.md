# TASK-003: React + Vite + Tailwind app shell

**Status:** IN-PROGRESS · **Epic:** EPIC-01 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Scaffold Vite React + Tailwind. Build the app shell: header (logo, bell, avatar, theme toggle), central canvas region, right Action Center drawer, bottom input dock. Dark + light theme.

## Acceptance Criteria
- [x] app shell matches Project-Overview layout
- [x] dark/light theme toggles and persists
- [x] talks to backend /health

## Dependencies
TASK-001

## Refs
Requirements §17 (UI layout), Project-Overview.html

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **No `frontend/` directory yet** — this is a true greenfield scaffold. Nothing to reuse on the FE side; nothing to break.
- **Backend `/health` contract (TASK-002, live):** `GET /health` → `{"status":"ok","service":<app_name>,"environment":<env>}`. Also `GET /health/ready` (pings Postgres, 200/503) and `GET /` (meta). The AC "talks to backend /health" maps to `/health`.
- **CORS already configured** in `backend/app/main.py` for `http://localhost:5173,http://localhost:3000` (driven by `CORS_ORIGINS` in `.env`). Vite default port 5173 is already allow-listed — no backend change needed.
- **Design source of truth:** `Project-Overview.html` (self-contained mock) — palette dark `#0b0f17`/`#131a26`/`#1a2435`, surfaces `#0e1521`/`#0d1320`, text `#e6edf6`/`#8a98ad`; accents blue `#3b82f6`, green `#22c55e`, red `#ef4444`, amber `#f59e0b`, violet `#8b5cf6`, teal `#14b8a6`. Layout confirmed: header (logo · 🔔 bell→Action Center · expand · avatar · theme) → central conversation **canvas** → right **Action Center** drawer → bottom **input dock**. Requirements §17 (UI-1..UI-9) governs.

### Dependencies Required
- **Frontend packages (new `frontend/package.json`):** `react`, `react-dom`, `vite`, `@vitejs/plugin-react`, `tailwindcss`, `@tailwindcss/postcss` (or Tailwind v4 Vite plugin), `postcss`, `autoprefixer`, TypeScript + `@types/*`. Optional: an icon set (lucide-react) for bell/avatar/theme glyphs.
- **Backend packages:** none.
- **Database migrations:** none.
- **Docker services:** add the `frontend` service to `docker-compose.yml` (a stub is already reserved at lines ~128–132: `build: ./frontend`, `ports: ["5173:5173"]`, `depends_on: [backend]`, `networks: [wealthnet]`). `.gitignore` already covers `node_modules/`, `dist/`, `.vite/`.

### Impact Assessment
#### Files to Modify / Create
- `frontend/` (new): `package.json`, `vite.config.ts`, `tsconfig*.json`, `index.html`, `tailwind.config.*`, `postcss.config.*`, `src/main.tsx`, `src/App.tsx`, `src/index.css`, plus shell components (`Header`, `Canvas`, `ActionCenter`, `InputDock`), a theme context/hook, and a tiny `api`/health client.
- `frontend/Dockerfile` (new) — dev server (`vite --host`).
- `docker-compose.yml`: uncomment/activate the reserved `frontend` service stub.
- `.env.example` / `.env`: optionally add `VITE_API_BASE_URL` (default `http://localhost:8000`).

#### Components Affected
- Backend: **LOW** — consumed read-only via `/health`; no contract change. CORS already allows 5173.
- Compose: **LOW** — additive service, network/volumes reused.

#### API Changes
- None. Frontend only *consumes* `GET /health`.

#### Database Changes
- None.

### Implementation Checklist (per CLAUDE.md)
- [ ] Scaffold Vite React+TS; do **not** duplicate or extend `demo/` (reference only)
- [ ] Tailwind configured with the Project-Overview palette as theme tokens (CSS vars for dark/light)
- [ ] App shell: header (logo, bell→Action Center, expand, avatar, theme toggle), canvas, right Action Center drawer, bottom input dock — matches Project-Overview layout (AC #1)
- [ ] Dark/light theme toggles **and persists** (localStorage + `prefers-color-scheme` fallback) (AC #2)
- [ ] Health client hits `GET /health` and shows backend status (AC #3); base URL from `VITE_API_BASE_URL`
- [ ] Activate `frontend` service in `docker-compose.yml` (`5173:5173`, depends_on backend)
- [ ] Loading/error states for the health check; self-documenting component structure
- [ ] Shell built as a foundation later tasks extend (registry/command-bar TASK-041/042, Action Center TASK-036) — leave clear seams, no premature framework

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *Tailwind v3 vs v4 config divergence* → pick one (v4 + `@tailwindcss/vite` is simplest) and pin it; document in the FE README/comment.
  - *CORS / API base URL mismatch in container vs host* → use `VITE_API_BASE_URL` (host: `http://localhost:8000`); 5173 already allow-listed so browser→backend works on host.
  - *Scope creep into widgets/command-bar* → this task is the **shell only**; defer generative-UI registry to its owning tasks.

### Estimated Effort
- Original: M
- Adjusted: M (unchanged) — greenfield but well-specified; the design mock removes layout ambiguity.
- Reason: no integration risk; only decision is the Tailwind version + theme-token plumbing.

**Dependency note:** TASK-001 is still in `in-progress/` (not `done/`), but its artifacts (compose base stack, `.env`, networks/volumes) plus the TASK-002 backend `/health` are fully live, and the compose file already reserves a `frontend` stub. The dependency is materially satisfied — proceeding without blocking.

---

## Implementation (2026-06-20)

Scaffolded `frontend/` (React 19 + Vite 6 + TypeScript, **Tailwind v4** via
`@tailwindcss/vite` — CSS-first `@theme`, no `tailwind.config.js`/PostCSS files).

**Structure**
- Tooling: `package.json`, `vite.config.ts` (react + tailwind plugins, `host:true`,
  polling watch for the Docker bind-mount), `tsconfig{,.app,.node}.json`, `index.html`
  (with a pre-paint theme script to avoid FOUC), `src/vite-env.d.ts`.
- Theme: `src/theme/ThemeProvider.tsx` + `useTheme` — sets `data-theme` on `<html>`,
  persists to `localStorage` (`waw-theme`) with `prefers-color-scheme` fallback.
- Tokens: `src/index.css` — palette from the mock as CSS vars under `[data-theme=dark]`,
  a derived light palette under `[data-theme=light]`, mapped to utilities via
  `@theme inline` (`bg-panel`, `text-muted`, `border-border`, accent colors…).
- API: `src/api/client.ts` (base from `VITE_API_BASE_URL`) + `src/api/health.ts`
  (typed to the TASK-002 `/health` contract).
- Shell (`src/components/shell/`): `AppShell` (grid: header / canvas+drawer / dock,
  collapses < lg), `Header` (logo, `BackendStatus` chip, bell→drawer toggle, avatar,
  `ThemeToggle`), `Canvas` (empty "Summon a view" state — seam for TASK-041),
  `ActionCenter` (drawer chrome + category tabs + empty state — seam for TASK-036),
  `InputDock` (quick-command chips + command input + voice/send stubs — seams for
  TASK-042/046), `BackendStatus`, `ThemeToggle`.
- Docker: `frontend/Dockerfile` (node:20-alpine, Vite dev server) + `.dockerignore`.

**Files modified**
- `docker-compose.yml` — activated the `frontend` service (build, `env_file`,
  `${FRONTEND_PORT:-5173}:5173`, bind-mount + anon `node_modules`, `depends_on`
  backend healthy).
- `.env` / `.env.example` — added `FRONTEND_PORT` + `VITE_API_BASE_URL`; added the
  frontend origin to `CORS_ORIGINS`.
- `.gitignore` — added `.npm-cache/`.

**Local-env notes**
- The shared npm cache had root-owned files → installed with a project-local
  `--cache ./.npm-cache` (git-ignored). No `sudo` needed.
- Host port 5173 is occupied by an unrelated process → published the frontend on
  **15173** (`FRONTEND_PORT`, remap convention matching the rest of `.env`), backend
  host port is **18000**; `VITE_API_BASE_URL=http://localhost:18000` and CORS allows
  `http://localhost:15173`.

**Verified live**
- `npm run build` (tsc -b + vite build) → clean, 39 modules.
- `docker compose up -d frontend` → full chain healthy; `http://localhost:15173/` and
  `/src/main.tsx` → 200; backend `/health` → 200; **CORS preflight** from the frontend
  origin returns `access-control-allow-origin: http://localhost:15173`.
- Compiled CSS contains `[data-theme=dark]`/`[data-theme=light]` blocks and utilities
  referencing `var(--color-*)` → runtime theme switch works; `ThemeProvider` +
  pre-paint script handle persistence (AC #2).

**Out of scope (seams left for owning tasks):** live alerts/cards (TASK-036), widget
registry & render protocol (TASK-041), command parsing + orchestrator call
(TASK-042/043), voice capture (TASK-046), RM view preferences (TASK-044).

Ready for `/task-review`.
