# TASK-060: Email ingestion via Microsoft Graph + entity extraction

**Status:** IN-PROGRESS · **Epic:** EPIC-08 · **Parent:** TASK-058 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Ingest emails as change events for the Change Radar. An email can reference an **instrument**
(internal "sell X" → fans out to all holders), a **client** (inbound correspondence → one
client), or the **book** (internal "de-risk growth"). Channel only decides parsing; output is
the same `{action, entity, source, ts, magnitude}` consumed by TASK-059.

## Acceptance Criteria
- [ ] Microsoft Graph client (Azure app registration, `Mail.Read`, client-credentials flow)
- [ ] Pull recent messages; dedup at **thread** level (rank the thread, not every reply)
- [ ] Local LLM (Gemma) classifies each email → `{action, entity(s), urgency/sentiment}` —
      Graph provides no sentiment, unlike Event Registry
- [ ] Identity mapping: `from`/`to` address → CRM client; unmatched senders bucketed, never dropped
- [ ] Direction handling: inbound (client→RM) drives impact; outbound is context only
- [ ] Internal "sell/trim X" emails resolve the instrument and fan out via TASK-059's join
- [ ] Azure-as-email-transport exception recorded in docs/Requirements.md

## Technical Approach
### Reuse
Local LLM abstraction (TASK-012) for extraction; CRM client identities (TASK-009/016) for
address matching; existing config/secrets handling (TASK-006) for Graph creds.
### New
Graph mail client + email→event normaliser + address→client resolver.

## Dependencies
TASK-006 (config/secrets) · TASK-009 (load CRM) · TASK-012 (LLM) · feeds TASK-059

## Refs
docs/Requirements.md (note the no-Azure-infra vs. Graph-transport distinction) · CLAUDE.md

---

## Technical Analysis (Auto-generated 2026-06-20)

**Key finding:** the consumer (TASK-059) is fully built and already *expects* this source.
`change_events.source` enumerates `email` as a valid value (`models/derived.py:275`), and TASK-059's
own AC calls out cross-channel dedup ("same event as news + email"). So this task does **not** touch
the radar scorer/fan-out — it produces normalised signals on the **same** `entity_key` grammar
(`isin:` / `sac:` / `client:` / `news:`) that `build_change_radar` already groups, scores and dedups.
The work is: (1) get emails in, (2) classify + resolve entities/identity, (3) emit signals the radar
picks up — plus **two structural blockers** that must be decided before coding (below).

### ⚠️ Open decisions (must resolve before implementation)

1. **Azure-Graph transport vs. no-Azure rule — and is there a real mailbox?**
   The project rule is hard "No Azure / no cloud dependency" (CLAUDE.md §"Target stack", memory
   `tech-stack`). This task deliberately carves out an **exception: Azure as email *transport*** (Graph
   reads a mailbox) ≠ Azure as *infrastructure* (compute/LLM/DB). The AC requires recording that
   exception in `docs/Requirements.md`. **But** there is no Azure tenant / mailbox wired in this repo
   (no `msal`/`azure-identity` in `requirements.txt`; no `MS_GRAPH_*` config). Two viable builds:
     - **(A) Real Graph client** — Azure app registration + `Mail.Read` client-credentials. Production
       path; demoable only if the team actually has a tenant + seeded mailbox on demo day.
     - **(B) Simulated email feed** — a `[SIMULATED]` canned-email seeder mirroring
       `loaders/simulate_client.py`, fed through the *same* normaliser. Offline, deterministic, matches
       the established demo pattern; the Graph client becomes an interface stub behind it.
   **Recommendation:** build the **normaliser + resolver first (channel-agnostic)**, ship **(B)** for the
   demo, and put the real Graph fetch behind a thin client interface so **(A)** drops in unchanged. This
   honours no-fallbacks (simulated data is explicitly `[SIMULATED]`-labelled, never silently faked) and
   the no-Azure rule for the demo path. **Needs RM/owner sign-off — it changes the AC scope.**

2. **CRM has no email-address field — identity mapping has nothing to join on.**
   `Client` carries only `name` (`models/source.py:27`); `Interaction.client_contact`/`rm_name` are
   **person names**, not addresses (`source.py:44`). The AC's "`from`/`to` address → CRM client" therefore
   needs a **new address↔client mapping** (new column on `Client`, or a small `client_email` table, or an
   LLM/name-similarity resolver). Unmatched senders must be **bucketed, never dropped** (AC + no-fallbacks).
   Decide the mapping mechanism before coding the resolver.

### Existing Resources Found (reuse — exact file:line)
- **LLM extraction:** `app/llm.py` — `json_chat(messages, schema)` (l.80) gives retried, fence-stripped,
  Pydantic-validated structured output. This is the classify-email→`{action, entity(s), urgency/sentiment}`
  primitive; pattern already used by `loaders/dna.py`. (TASK-012 ✓ done.)
- **Config/secrets:** `app/config.py` `Settings` (l.49) + `missing_secrets()` (l.205) — add `ms_graph_*`
  fields here and a `MissingSecret` entry so the capability degrades with a startup warning, not a crash.
  `httpx` is already a dependency (l. requirements) → client-credentials OAuth + Graph REST need **no new
  package** unless we prefer `msal`. (TASK-006 ✓ done.)
- **Radar consumer:** `loaders/change_radar.py` `build_change_radar()` (l.179) — entity grouping (l.332),
  `score_event` (l.125), `RadarSignal` dataclass (l.82), `extract_alert_entity` (l.139). Email signals must
  land on the same `entity_key` so they dedup with drift/news on the same instrument. `source="email"`.
- **Simulated-feed precedent:** `loaders/simulate_client.py` (`[SIMULATED]` canned data, delete-and-reload
  idempotency, LLM-with-citations, fail-loud-if-LLM-unreachable) — the exact template for build (B).
- **CRM identity:** `Client` (`source.py:22`), `Interaction` (`source.py:34`), persona names in
  `loaders/personas.py:42`. Note: **no email field exists** (see open decision 2).
- **Pipeline wiring:** `loaders/personas.py:120` runs `build_change_radar` as step 14; an email-ingest step
  must run **before** it. Seed routes live in `routers/admin.py`; latest migration is
  `migrations/versions/0011_change_events.py` → a materialised email table would be `0012_*`.

### Dependencies Required
- **Frontend:** none (radar UI already consumes `change_events`; `source="email"` renders via existing path).
- **Backend packages:** **none required** if Graph is called over `httpx` (already pinned). Optional
  `msal` if we prefer the SDK for token acquisition. Build (B) needs nothing new.
- **Config:** new `MS_GRAPH_TENANT_ID / CLIENT_ID / CLIENT_SECRET / MAILBOX` (+ `missing_secrets` entries).
  Only needed for build (A).
- **DB:** optional. Either emit signals straight into the radar build (no table), or materialise an
  `email_events` table (migration `0012_*`) for traceability. Lean **table** here (unlike TASK-059's
  query-time lean) because emails are an *external* source with no other system of record — they need
  somewhere to live for the "every claim cites its source" rule.

### Impact Assessment
#### Files to Modify
- `app/config.py` — add `ms_graph_*` settings + `missing_secrets()` entry. LOW.
- `app/loaders/personas.py` — insert email-ingest step before step 14 (radar). LOW.
- `app/loaders/change_radar.py` — only if email events are a new source table the builder must read;
  if emails reuse the Alert/NewsItem path, **no change**. LOW–MEDIUM.
- `app/routers/admin.py` — add `POST /admin/seed/emails` (or `/ingest/emails`). LOW.
- `docs/Requirements.md` — record the Azure-as-transport exception (AC). LOW.
#### New Files
- `app/loaders/email_ingest.py` — Graph client (interface) + email→`{action, entity, source, ts, magnitude}`
  normaliser + thread-level dedup + address→client resolver + direction (inbound drives impact / outbound
  context-only) + internal "sell X" → instrument fan-out.
- `app/loaders/simulate_emails.py` (build B) — `[SIMULATED]` canned email feed through the same normaliser.
- `backend/migrations/versions/0012_email_events.py` — only if materialising.
- `backend/tests/test_email_ingest.py` — pure-fn tests (classify mapping, thread dedup, direction,
  address resolution incl. unmatched-bucket), following `test_change_radar.py` / `test_news.py` style.
#### Database Changes
- New optional `email_events` table (entity-keyed, indexed on the triggering entity), or none.
#### API Changes
- Additive `POST /admin/seed/emails`; no change to `GET /radar` contract.

### Implementation Checklist (CLAUDE.md principles)
- [ ] **Resolve open decisions 1 & 2 with the owner first** (Azure-transport scope + identity-mapping mechanism).
- [ ] Reuse `llm.json_chat` for classification — do **not** add a parallel LLM call path.
- [ ] Channel-agnostic normaliser: output is exactly `{action, entity, source="email", ts, magnitude}`,
      entity carries its type (`instrument|client|macro`) driving the radar resolver — channel only parses.
- [ ] Dedup at **thread** level (rank the thread, not every reply); cross-channel dedup via the shared
      `entity_key` so an email + news on the same instrument collapse (TASK-059 AC).
- [ ] Direction: inbound (client→RM) drives impact; outbound is context-only. Internal "sell/trim X" →
      resolve instrument → fan out via the radar's instrument→holders join.
- [ ] Identity: address→client; **unmatched senders bucketed, never dropped** (no-fallbacks).
- [ ] Graph gives **no sentiment** (unlike Event Registry) — derive urgency/sentiment in the LLM step.
- [ ] No-fallbacks: simulated feed (build B) is explicitly `[SIMULATED]`-labelled; LLM-unreachable fails loud.
- [ ] Record the Azure-as-email-transport exception in `docs/Requirements.md` (AC).
- [ ] Tests: classify mapping, thread dedup, inbound/outbound, instrument fan-out, unmatched bucket.

### Risk Analysis
- **Risk Level:** MEDIUM-HIGH (driven by the two open decisions, not by code volume).
- **Main Risks:**
  - *No real mailbox / Azure tenant on demo day* → build (A) is undemoable. Mitigation: ship build (B),
    Graph behind an interface.
  - *No CRM email field* → resolver has nothing to join; risk of silently dropping senders. Mitigation:
    decide mapping up front; explicit unmatched bucket (no-fallbacks).
  - *Duplicate fan-out / scoring path* → re-implementing what `build_change_radar` already does.
    Mitigation: emit on the shared `entity_key`; touch no scorer code.
  - *No-Azure rule violation in the demo path*. Mitigation: simulated transport for demo; Azure used only
    as documented transport exception, never as infra.

### Estimated Effort
- Original: **M**. Adjusted: **M** for build (B) (normaliser + resolver + simulated feed + tests, all on
  existing primitives); **M+/L** if build (A) real-Graph + a new `email_events` table + migration is in
  scope. The two open decisions, not the code, set the final size.
