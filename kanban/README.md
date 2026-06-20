# Kanban Board — Wealth Advisor Workbench

Columns (move task files between folders as they progress):
`backlog/` → `in-progress/` → `review/` → `done/`

`epics/` holds the parent EPIC files (they don't move; tick their sub-tasks).

## Conventions
- Tasks: `TASK-NNN-slug.md`; Epics: `EPIC-NN-slug.md`.
- Priority: **P0** = MVP must · **P1** = should · **P2** = could / roadmap.
- Effort: S (<1d) · M (1–3d) · L (3–5d).
- Each task links to `docs/Requirements.md` sections / UC ids it implements.

## Epics
| Epic | Theme | Priority |
|---|---|---|
| EPIC-01 | Infrastructure & scaffolding | P0 |
| EPIC-02 | Data ingestion & domain model | P0 |
| EPIC-03 | Provider integrations (LLM/SIX/News) | P0 |
| EPIC-04 | Client DNA Builder (UC-1) | P0 |
| EPIC-05 | Personalization engine (UC-4, §11/§12) | P0 |
| EPIC-06 | Portfolio & news linkage (UC-2, §13) | P0 |
| EPIC-07 | News monitoring loop (§14) | P1 |
| EPIC-08 | Alert engine (UC-3, §15) | P0 |
| EPIC-09 | Message generation (UC-5, §16) | P0 |
| EPIC-10 | Generative UI / canvas (§17/§18) | P0 |
| EPIC-11 | Voice & notes (UC-28, §19.1) | P1 |
| EPIC-12 | Tasks & autonomous execution (UC-29, §19.2) | P1 |
| EPIC-13 | Orchestration — LangGraph (§20 ST5) | P1 |
| EPIC-14 | Demo, seed data & pitch (D1–D4) | P0 |

Source of truth: `docs/Requirements.md`. Architecture: `Project-Overview.html`.
