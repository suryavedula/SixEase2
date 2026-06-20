# EPIC-02: Data ingestion & domain model [EPIC]

**Status:** BACKLOG · **Priority:** P0 · **Type:** epic · **Created:** 2026-06-20

## Goal
Parse the provided workbooks and load the domain entities (notes, positions, CIO list, mandates) into Postgres; build the instrument tag layer and synthetic clients.

## Business value
Real challenge data is queryable; the engine and UI render from DB, not ad-hoc parsing.

## Sub-tasks
- [ ] TASK-007: Stdlib XLSX parser for CRM + Portfolio workbooks
- [ ] TASK-008: Load portfolios, CIO list, mandate strategies into DB
- [ ] TASK-009: Load CRM interaction notes into DB
- [ ] TASK-010: Instrument value-tagging layer (region/sector/value tags, E5)
- [ ] TASK-011: Synthetic client generator (~100 grounded, seeded — D2/D4)

## Refs
docs/Requirements.md · Project-Overview.html (Architecture)
