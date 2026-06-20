# EPIC-07: News monitoring loop (§14) [EPIC]

**Status:** BACKLOG · **Priority:** P1 · **Type:** epic · **Created:** 2026-06-20

## Goal
Continuous firehose-filter poller with newestUri cursor, inverted-index fan-out, LLM triage on shortlist, event-cluster dedup; seeded triggers for the demo.

## Business value
'24/7 the moment it breaks' made real and cost-bounded.

## Sub-tasks
- [ ] TASK-029: Firehose-filter poller + newestUri cursor + Redis queue (F1/F2)
- [ ] TASK-030: Inverted-index fan-out + LLM triage on shortlist (F3/F4)
- [ ] TASK-031: Event-cluster dedup + seeded persona trigger articles (F5/§14.4)

## Refs
docs/Requirements.md · Project-Overview.html (Architecture)
