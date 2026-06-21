# Requirements — Wealth Advisor Relationship Workbench

> Status: draft / brainstorm. Captures the product vision and candidate use cases as
> requirements. Not all are in scope for the 48h build — see Prioritisation at the end.

## 1. Problem & Target

**Problem.** A relationship manager (RM) cannot track everything about every client, so
hyper-personalised, "feel-known" service is today reserved for a handful of clients. The
rest get generic treatment. In an increasingly AI-mediated world, the scarce, valued thing
is genuine human connection — and the RM has no time to scale it.

**Target user.** The relationship manager. The system serves the RM; it never advises the
client directly.

**Positioning — companion, not a CRM.** This is NOT a CRM and does not aim to build or
replace one. The bank already has a CRM (the system of record). Our product is a layer that
sits *on top of* the existing CRM, reads its data, and turns it into relationship insight
and action. We consume CRM data; we do not own it.

**Core principle.** The AI remembers everything so the human can show up as if they
remembered everything. AI suggests and explains; the RM recommends; the client decides.

## 2. Actors

- **RM** — primary user; reviews, edits, decides, acts.
- **Client** — never interacts with the AI directly; experiences only the human RM.
- **System** — the agent workbench layered on top of the CRM (orchestrator + Portfolio /
  News / Message capabilities reading from the CRM data source).
- **CRM (system of record)** — external, pre-existing. Source of conversation logs and
  client data. The system reads from it and MAY write drafts/notes back; it does not
  replace it.
- **CIO recommendation list** — external constraint on the swap universe.

## 3. Global / Non-functional requirements

- **G1 — Human in the loop.** The system SHALL NOT contact the client directly. Every
  outbound communication is produced as a *draft* the RM can edit, approve, or discard.
- **G2 — Traceability.** Every alert, suggestion, and drafted message SHALL cite its
  evidence: the specific CRM note(s), portfolio position(s), and/or news event(s) that
  produced it, each linkable to its source.
- **G3 — Explainability.** Every suggestion SHALL state *why* in plain language and expose
  a confidence level. When confidence is low, the system SHALL say so and defer to the RM.
- **G4 — Strategy preserved.** Personalisation happens at the asset level only. The
  client's mandate (Defensive / Balanced / Growth) and the CIO sub-asset-class targets are
  NOT changed by the system.
- **G5 — Suitability.** Any proposed action SHALL be checked against the client's mandate
  and stated constraints before being surfaced; conflicts are flagged, not hidden.
- **G6 — Data provenance.** The system SHALL distinguish facts derived from real data from
  AI inferences, and label inferences as such.
- **G7 — CRM-augmenting, not replacing.** The system SHALL treat the existing CRM as the
  system of record. It reads CRM data and MAY write back drafts, notes, or completed
  actions, but SHALL NOT require the bank to migrate off or replace its CRM. The product is
  valuable as an add-on layer.

## 4. Core capabilities (from the challenge)

### UC-1 — Build the Client DNA
- The system SHALL read raw CRM conversation logs *from the existing CRM* and construct a
  structured "investment identity" per client: values, business context, family context,
  personal priorities, risk temperament, and preferred communication style.
- DNA is a derived/enrichment layer over CRM data, not a new system of record (G7).
- DNA SHALL be built automatically from notes, with no manual data entry required.
- Each DNA attribute SHALL link to the source note(s) in the CRM that established it (G2).

### UC-2 — Connect Portfolio & News
- The system SHALL link a client's DNA to their current holdings and to a live news feed.
- Holdings SHALL be resolvable to market data via SIX (Valor + MIC) identifiers.

### UC-3 — Surface Relevant Alerts
- The system SHALL match each client's DNA against their portfolio and incoming news to
  flag conflicts (a holding contradicts a value) and opportunities.
- Alerts SHALL be ranked by relevance to the individual client, not by generic salience.

### UC-4 — Suggest Personal Asset Swaps Within the Strategy
- When a holding conflicts with the client's DNA, the system SHALL propose a replacement
  **from the same sector** that fits both the strategy and the client.
- The swap universe SHALL be constrained to the CIO recommendation list (BUY/HOLD/SELL).
- Each swap SHALL show the rationale, the DNA conflict it resolves, and mandate impact.

### UC-5 — Personalise the Advisory Message
- For every proposal the system SHALL produce a draft RM message in the client's preferred
  style (e.g. data-driven/analytical vs. values-led/purpose-driven).
- The same recommendation SHALL be expressible in different voices without changing facts.

## 5. Relationship-layer use cases (the differentiator)

These extend the core toward "make the client feel known." Each is a candidate requirement.

### UC-6 — Moments That Matter (non-financial actions)
- The system SHALL recognise events where the best next action is **not a trade** (e.g. a
  development affecting a client's foundation/cause) and surface a personal-outreach
  suggestion instead of a swap.
- Each moment SHALL state the suggested human action and what to acknowledge.

### UC-7 — Pre-call brief ("pick up where you left off")
- Before a client interaction the system SHALL generate a short brief: what the client
  cares about, open promises, recent life events, and one personal item to mention.

### UC-8 — Promise tracking
- The system SHALL extract soft commitments made by the RM in CRM notes ("I'll look into
  X") and track them to completion, reminding the RM of outstanding promises.

### UC-9 — Quiet-client radar
- The system SHALL identify clients with no meaningful recent contact, weighted by
  relationship/emotional risk (not only AUM), so none fall through the cracks.

### UC-10 — Panic / behavioural radar
- On market stress the system SHALL rank clients by likelihood to react badly (per their
  documented temperament) and draft pre-emptive reassurance for each.

### UC-11 — Values-drift detection
- Over the multi-year note history the system SHALL detect when a client's values or
  circumstances have evolved and flag where the portfolio or the RM's model of the client
  has fallen behind.

### UC-12 — Relationship health score
- The system SHALL compute a per-client connection indicator (recency, promises kept,
  sentiment trend, life-event coverage) distinct from portfolio value.

### UC-13 — Style-matched drafting
- Drafted messages SHALL match the client's communication style and the emotional register
  of the moment (celebratory, sober, reassuring), never a fixed template.

## 6. New use cases (wave 2 — to make it special)

### UC-14 — Anticipatory life-stage planning
- The system SHALL detect life-stage signals in notes (new child, approaching retirement,
  child turning 18, business sale) and surface the relevant planning opportunity *before*
  the client raises it.

### UC-15 — Behavioural guardrail ("you said you'd never")
- When a proposed/CIO action conflicts with a client's stated red line (e.g. Räber's
  aversion to US tech), the system SHALL flag the conflict AND draft a respectful rationale
  for declining or adapting it — protecting the client from a misaligned recommendation.

### UC-16 — Self-words reminder (anti-panic)
- The system SHALL be able to surface a client's own past statements ("I'm a long-term
  investor, I don't react to noise") to help the RM steady them during volatility.

### UC-17 — Good-news monitoring (inverse alert)
- Beyond risk, the system SHALL monitor for positive developments tied to a client's
  interests/cause (a research breakthrough, a milestone) and surface them as
  relationship-building moments.

### UC-18 — Relationship continuity on RM handover
- When a client moves to a new RM, the full Client DNA, history, and open promises SHALL
  transfer so the relationship does not reset to zero.

### UC-19 — Cultural & linguistic fit
- Drafts SHALL respect language and formality conventions (e.g. Swiss German, formal vs.
  informal address) inferred from the client's profile.

### UC-20 — Bad-news delivery coaching
- When delivering a loss or negative event, the system SHALL tailor the framing to the
  client's temperament and provide the RM guidance on how to have the conversation.

### UC-21 — Sentiment trajectory
- The system SHALL show whether a relationship is warming or cooling over time, derived
  from the tone/content trend across the note history.

### UC-22 — Report annotation
- The system SHALL be able to annotate standard portfolio reports with personal context
  ("this ESG fund aligns with your reforestation interest"), turning generic output
  personal.

### UC-23 — Next-gen / family engagement
- The system SHALL detect family/next-generation mentions and flag opportunities to engage
  the broader family before wealth transfers away.

### UC-24 — RM time allocation ("relationship ROI")
- Given the RM's limited hours, the system SHALL suggest where to invest relationship time
  this week for maximum relationship benefit, factoring urgency and emotional risk.

### UC-25 — Devil's-advocate view
- For any recommendation the system SHALL be able to present the counter-argument so the RM
  sees both sides before deciding.

### UC-26 — Calibration / trust receipts
- The system SHALL keep a record of past suggestions and their outcomes so the RM can
  calibrate how much to trust the AI over time.

### UC-27 — Onboarding companion (first 100 days)
- For a new client the system SHALL accelerate DNA-building by prompting the RM for the
  highest-value missing information, so trust is established quickly.

## 7. Test data requirements

- **D1.** The system SHALL be demonstrable against the four challenge personas (Schneider,
  Huber, Räber, Ammann) using the provided CRM and Portfolio workbooks.
- **D2.** Where live APIs are unavailable, synthetic-but-grounded data (CRM notes, news
  events, life events) SHALL be generatable per persona to exercise each use case
  end-to-end, consistent with the real persona profiles.
- **D3.** Each persona SHALL have at least one scripted trigger event that exercises a
  distinct use case (a swap, a non-financial moment, a behavioural guardrail, a good-news
  moment) for the demo.

## 8. Prioritisation (proposed)

- **Must (the literal challenge):** UC-1, UC-2, UC-3, UC-4, UC-5, plus G1–G4.
- **Should (the differentiator):** UC-6 (Moments That Matter), UC-7 (pre-call brief),
  and full traceability (G2/G3) — this is where the Creativity + Trust score is won.
- **Could (memorable extras if time allows):** UC-11, UC-15, UC-17, UC-25.
- **Won't (this build):** the rest — kept here as roadmap.

## 9. Open questions

- Which single demo scene best proves the thesis? (Candidate: one news event → two
  personas → two *different* human responses, one a swap, one a call, each traceable.)
- How much of the DNA is extracted live by an LLM vs. pre-computed for demo reliability?
- What is the minimal data model for Client DNA? (To be defined.)
- Where do outputs live — written back into the CRM, or held in our own workbench UI?

## 10. Data inventory (provided datasets, inspected)

### 10.1 CRM workbook — `data/SwissHacks CRM.xlsx`
- Four tabs, one per persona: `CRM Raeber`, `CRM Schneider`, `CRM Huber`, `CRM Ammann`.
- Columns: `Date` (Excel serial number, ~2023 → 2026), `Medium` (Phone / Lunch / Email /
  Physical Meeting / Video / File Note / Event), `RM Name`, `Client Contact`, `Note`.
- ~25 free-text, chronological notes per client. Identity is narrative, not fielded — DNA
  must be *extracted*, not read off columns.
- The Schneider tab alone evidences: identity emerging over 3 years; an **RM handover**
  (Thomas Keller → Sarah Meier, with file notes) — see UC-18; the trigger event (daughter
  Chloe diagnosed with early-onset Parkinson's → family foundation); and an explicit,
  verbatim **red line** ("If a company we own ever abandons or defunds Parkinson's research
  … Flag them immediately for divestment") — a machine-actionable hard exclusion (UC-15).

### 10.2 Portfolio workbook — `data/SwissHacks Portfolio Construction.xlsx`
Ten sheets: `README`, `Portfolio Strategies`, `CIO Recommendation List`,
`Sample Portfolio {Defensive,Balanced,Growth}`, `Transactions {Defensive,Balanced,Growth}`,
`Cash Flows`.

- **`Portfolio Strategies`** — 12 sub-asset-class target weights per mandate; each mandate
  sums to CHF 10,000,000. This is *the invariant* (see §11).
- **`CIO Recommendation List`** — 172 rows: **55 BUY / 113 HOLD / 4 SELL**. Columns:
  `Rating`, `Rating Since`, `Asset Class`, `Sub-Asset Class`, `Region`, `Industry Group`,
  `Issuer / Asset`, `Security / Details`, `ISIN`, `CIO View`, `Valor`, `MIC`,
  `Yahoo Ticker`, `As Of`. Contains not-held **BUY swap candidates**. The 4 SELLs each say
  "Replace within <Industry Group>": China Mobile (Telecom/EM), ExxonMobil (Energy/US),
  Intel (IT/US), Albemarle (Materials/Global).
- **`Sample Portfolio *`** — positions with `Sub-Asset Class`, `Industry Group`, `Region`,
  `Issuer`, `ISIN`, `Target (CHF)`, `Current (CHF)` (drifted), `Valor`, `MIC`, `Yahoo`.
- Distinct **Industry Groups (19):** Communication Services, Consumer Discretionary,
  Consumer Staples, Digital Assets, Diversified ETF, Energy, Financials, Government Bonds,
  Health Care, Industrials, Information Technology, Investment Grade, Materials, Precious
  Metals, Private Markets, Real Estate (Fund), Real Estate (REIT), Telecommunication,
  Utilities. Distinct **Regions:** Schweiz, Europa, USA, Emerging M., Global.

### 10.3 Conventions (from the README sheet)
- All amounts CHF; ISIN per ISO 6166; equities at real historical closes, bonds at par
  (qty = face ÷ 100); cash positions use `Cash-XXX`.
- **Drift rule:** a sub-asset class may deviate at most **±2.0 pp** from target (recomputed
  against the drifted total); breaches require a rebalance proposal. Balanced & Growth ship
  with deliberate breaches.
- Identifiers: `{Valor}_{MIC}` for SIX listing tools; ISIN (`instrument_symbology`) for
  bonds (blank Valor/Yahoo). Dates are Excel serials needing conversion.

### 10.4 Engine ↔ data mapping
| Engine concept | Data source |
|---|---|
| Invariant (never altered) | `Portfolio Strategies` sub-asset-class weights |
| Same-slot / same-sector match key | `Sub-Asset Class` + `Industry Group` |
| Swap universe (CIO BUY only) | `CIO Recommendation List`, `Rating = BUY` |
| Drift breach trigger | `Current` vs `Target` weights, ±2.0 pp |
| Stale SELL alert | `Rating = SELL` on a held position + `Rating Since` age |
| Client hard exclusions / tilts | extracted from CRM notes (e.g. Schneider's red line) |
| Traceability receipts | `CIO View` + source CRM note + ISIN |

## 11. Personalization-engine requirements (deepens UC-4)

- **E1 — Invariant.** The sub-asset-class target weights (`Portfolio Strategies`) are fixed
  per mandate and SHALL NOT be altered by personalization.
- **E2 — Free variable.** Personalization changes only *which instrument* fills a slot.
- **E3 — Match key.** "Same sector" SHALL be defined as same `Sub-Asset Class` +
  `Industry Group`.
- **E4 — Swap universe.** A valid swap candidate SHALL be CIO `BUY`, in the same Industry
  Group, and not currently held.
- **E5 — Instrument value-tagging.** Each instrument SHALL carry tags (region, sector, and
  value/controversy tags such as us-tech, fossil, deforestation-risk, neuro-research,
  labour-risk, luxury) so client DNA can be matched against holdings.
- **E6 — Client constraints.** DNA SHALL yield hard exclusions and soft tilts expressed
  against those tags.
- **E7 — Fit score.** The system SHALL compute an explainable, deterministic per-holding
  and per-portfolio fit score; an LLM MAY write the human-readable rationale but SHALL NOT
  be the source of the score (auditability — G3).
- **E8 — Risk-neutral swap.** A proposed swap SHALL preserve the slot's sub-asset-class
  weight (like-for-like on risk), so the mandate is provably unchanged (G4).
- **E9 — Precedence.** When constraints collide, order is: mandate > compliance/suitability
  > client hard exclusion > CIO universe > client soft optimization.
- **E10 — Drift & stale-SELL detection.** The system SHALL flag sub-asset-class drift
  breaches (±2.0 pp) and SELL-rated held positions, with age since rating.
- **E11 — No compliant swap.** If no candidate satisfies E4 + exclusions, the system SHALL
  keep the holding and explain why, optionally escalating as a Moment That Matters (UC-6).
- **E12 — No churn.** A swap SHALL be proposed only when the fit gain exceeds a threshold
  (account for turnover / tax / cost).

## 12. Scale-proof requirement

- **D4 — Personalization at scale.** To demonstrate the thesis, the system SHALL be
  exercisable over a population of ~100 synthetic clients, grounded in the four real
  archetypes below with varied exclusions, tilts, mandates, and communication styles, and
  SHALL produce a **book view**: per-client fit scores plus a ranked queue of swap
  proposals — all derived from the *same* fixed strategy, each client's queue different.
  Synthetic data SHALL be reproducible (seeded) and clearly labelled synthetic (G6).

Reference archetypes (from the personas), each expressed as exclusions/tilts:
- **Defensive Value (Räber):** exclude US tech; tilt Swiss/European quality; Defensive.
- **Purpose / ESG (Huber):** exclude fossil & deforestation-risk; tilt sustainability;
  Defensive/Balanced.
- **Corporate Reputation (Ammann):** exclude labour/controversy risk; tilt luxury/quality;
  Growth.
- **Personal Cause / Health (Schneider):** exclude pharma that defunds neuro research; tilt
  neuro-research / healthcare; Balanced.

## 13. Connect to Portfolio & News — detailed requirements (deepens UC-2)

**Core principle — two axes of relevance.** A news item matters to a client because it
touches either (a) **what they own** (a holding) or (b) **what they care about** (a DNA
value/cause/theme), even when no holding is involved. The system SHALL link news on *both*
axes; the thematic axis is what surfaces non-financial Moments That Matter (UC-6).

**Per-client watchlist.** The system SHALL derive, per client, a watchlist =
(held entities) ∪ (DNA themes), and monitor the live news feed against it. News is filtered
to this watchlist — generic market noise is excluded.

### 13.1 Portfolio linkage (P)
- **P1.** The system SHALL load each client's holdings from their mandate's sample portfolio
  and associate them with the client profile.
- **P2.** Each holding SHALL be resolved to market identifiers (`{Valor}_{MIC}` listing,
  `ISIN`, `Yahoo Ticker`) and valued via live SIX market data, degrading gracefully to the
  workbook `Current (CHF)` (and par-pricing for bonds / thin venues) when live data is
  unavailable.
- **P3.** The system SHALL compute current market value, sub-asset-class weights, and drift
  vs. target per holding and per sub-asset class (feeds E10).
- **P4.** Each holding SHALL be annotated with (i) entity identifiers — issuer name +
  aliases, ticker, ISIN — for news matching, and (ii) region/sector/value tags (E5) for DNA
  matching. This annotation is the join that links portfolio ↔ DNA ↔ news.
- **P5.** Portfolio linkage SHALL be refreshable on demand and on a schedule (24/7
  monitoring intent), not a one-off snapshot.

### 13.2 News linkage (N)
- **N1.** The system SHALL connect to a live news + sentiment feed (Event Registry /
  newsapi.ai as primary; Tenity MCP-News, Yahoo Finance, or Google News as alternatives).
- **N2.** For each client the system SHALL issue two query sets: (a) **entity queries** from
  held issuers/tickers; (b) **thematic queries** from DNA tags, values, causes, and
  business context (e.g. Parkinson's-research funding, palm-oil deforestation, labour
  scandal, US AI stocks).
- **N3.** Each article SHALL be linked to the specific holding(s) and/or DNA theme(s) it
  matches, with a relevance score and a sentiment score.
- **N4.** Results SHALL be deduplicated and ranked by recency × relevance × impact; only
  watchlist-relevant items are retained.
- **N5.** Every linked article SHALL retain source, URL, and timestamp for traceability
  (G2), and SHALL be the citeable evidence behind any downstream alert.

### 13.3 Relevance & impact bridge (R) — feeds UC-3 / UC-6
- **R1.** An article is **relevant** to a client iff it matches a held entity (own-axis) OR a
  DNA theme (care-axis).
- **R2.** The system SHALL classify impact as: **threat** (conflicts with a holding or
  value → candidate swap/alert, UC-3/UC-4), **opportunity** (good news / swap candidate /
  cause milestone, UC-17), or **non-financial moment** (cause- or person-related, best
  answered by outreach not a trade, UC-6).
- **R3.** Relevance/impact scoring SHALL be explainable: it states which holding or theme
  matched and why (G3).

### 13.4 Open questions (UC-2)
- Entity matching by keyword vs. Event Registry concept URIs (more precise, needs
  resolution step) — which for the demo?
- News polling cadence for "24/7" — real scheduler vs. on-demand refresh for the demo?
- Live SIX pricing vs. cached/workbook values for demo reliability and rate limits?

## 14. Technical feasibility — Monitor Global News 24/7

**Decision:** the news backbone is **Event Registry / newsapi.ai** (REST). SIX MCP supplies
financial data. Phoeniqs supplies the LLM. (News source confirmed by the team.)

**Verdict: feasible.** Near-real-time monitoring is a first-class capability of Event
Registry. The only honest caveat: latency is *minutes* (polling-based), not instant — frame
to users as "near-real-time," not "the literal second it publishes."

### 14.1 Verified API facts (newsapi.ai)
- **Near-real-time feed:** `GetRecentArticles.getUpdates()` (minute stream) or
  `QueryArticles` + `RequestArticlesRecentActivity`. A polling loop (≈60s) with a
  **`newestUri` cursor** (`updatesAfterNewsUri` / `updatesafterBlogUri`) gives **gapless,
  duplicate-free** coverage. Recommended interval 1–10 min; batch max 100 (up to 2000).
- **Server-side filters** on the stream: `keywords`, `conceptUri` (OR logic),
  `sourceLocationUri`, language — so only watchlist-relevant items are pulled.
- **Concept URIs** enable precise entity matching (resolve issuer → concept URI), avoiding
  name-collision false positives.
- **Per-article sentiment** is returned (used for impact scoring, R2).
- **Limits:** max **5 concurrent requests** (else HTTP 429); token-based — **1 token per
  recent-news search** (historical 5–15); free tier 2,000 tokens; extra tokens $0.015 each.

### 14.2 Architecture — firehose-filter with local fan-out
- **F1.** The system SHALL maintain a **global watchlist index** = the union of all clients'
  entity concept-URIs and DNA themes/keywords (clients share entities, so the distinct set
  grows sublinearly with client count).
- **F2.** A **single sequential poller** SHALL query the recent-activity feed filtered to the
  global watchlist on a fixed interval, advancing the `newestUri` cursor each cycle (gapless,
  and one sequential poller respects the 5-concurrent-request limit).
- **F3.** Each returned article SHALL be matched locally via an **inverted index**
  (concept/theme → set of clients) — O(article) fan-out, no per-client API calls.
- **F4.** A cheap pre-filter (entity/keyword/sentiment) SHALL shortlist candidates; the LLM
  (Phoeniqs) SHALL run only on the shortlist for impact classification (R2) and draft
  generation — never on every article (cost control).
- **F5.** Breaking-story dedup SHOULD use Event Registry **event clustering** so one story
  surfaces once, not once per source.
- **F6.** Live prices for affected holdings come from **SIX** (`intraday_snapshot` /
  `end_of_day_snapshot`), independent of the news token budget.

### 14.3 Cost & latency envelope
- **Polling cost:** ~1 token/poll → 5-min interval ≈ 288 tokens/day (~8.6k/mo, ≈ $130/mo at
  $0.015); 1-min interval ≈ $650/mo. Tunable; on-demand fallback for the demo.
- **End-to-end latency:** publication → indexed (minutes) + poll interval (1–10 min) ⇒
  "near-real-time" of a few minutes. Acceptable for RM workflows; not HFT.

### 14.4 Demo vs. production tiers
- **Demo (48h):** on-demand "Scan news" per watchlist via `/article/getArticles` (the
  reference demo already does this), OR a 5-min poller over a small watchlist for a "live"
  feel. The four persona trigger articles SHALL be **seeded/snapshotted** so the demo lands
  even if live coverage is thin or the API rate-limits (G6: label seeded data).
- **Production:** the §14.2 filtered minute-stream poller + cursor + inverted-index fan-out
  + LLM triage on shortlist + event-cluster dedup + push to the RM queue. Standard
  event-driven design.

### 14.5 Risks & mitigations
- **Thin coverage of niche events** (e.g. a specific pharma defunding a research division) →
  broaden thematic queries; rely on Event Registry's large source base; seed for demo;
  optional Yahoo/Google News fallback.
- **Entity name collisions** → use `conceptUri`, not raw keywords.
- **Batch overflow (>100/min in busy windows)** → page within the interval via `newestUri`,
  or shorten interval.
- **Token-budget exhaustion** → tune interval, cache, on-demand fallback; the 5-concurrent
  cap is respected by the single-poller design.
- **Demo fragility** → snapshot the trigger articles; never depend on a live hit mid-pitch.

Sources: [newsapi.ai docs](https://newsapi.ai/documentation) ·
[pricing/limits](https://newsapi.ai/plans) ·
[recent-articles feed example](https://github.com/EventRegistry/event-registry-python/blob/master/eventregistry/examples/FeedOfNewArticlesExamples.py)

## 15. Alert engine (deepens UC-3)

The alerts queue is the convergence point: linked news (§13), drift / stale-SELL (E10),
DNA conflicts (UC-4), and relationship signals all surface here.

**Core principle — not every alert is a trade.** Each alert carries an implied **action
type**, and the same event may fire more than one alert (e.g. a pharma defunding research →
both a *swap* alert and a *reach-out* alert; the RM chooses).

- **AL1 — Generation.** Alerts SHALL be generated from: linked news impact (R2);
  sub-asset-class drift breach and stale CIO SELL (E10); DNA conflict without news (UC-4);
  CIO action conflicting with a client red line (UC-15); good news on a client's cause
  (UC-17); quiet client / overdue promise (UC-9 / UC-8); panic risk on volatility (UC-10);
  values drift (UC-11).
- **AL2 — Action type.** Every alert SHALL carry an implied action ∈ {**Trade**
  (swap/rebalance), **Reach out** (human moment, UC-6), **Acknowledge/Inform** (FYI),
  **Watch** (not yet actionable)}. Not every alert is a trade.
- **AL3 — Anatomy.** An alert SHALL carry: client, class, severity, timestamp, status,
  trigger + evidence (citeable, G2), a "why this matters to *you*" tied to the DNA
  attribute and its source note, a suggested next-best-action (+ draft message where
  applicable), and confidence (G3).
- **AL4 — Severity tiers.** `Critical` (act now) · `Attention` (this week) · `FYI`.
- **AL5 — Noise control.** The system SHALL suppress fatigue via: event-cluster dedup (one
  story → one alert), threshold gating (no swap unless fit-gain clears the bar, E12),
  cooldown (no daily re-fire of the same conflict), and per-client aggregation (roll small
  signals into one "needs attention" card).
- **AL6 — Prioritisation.** Alerts SHALL be ranked by impact × relevance × urgency ×
  emotional-weight — explicitly **not** by AUM (UC-24). The §12 book view is this ranked
  queue across all clients.
- **AL7 — Lifecycle (human-in-the-loop, G1).** surface → RM reviews evidence → act /
  dismiss / snooze / convert-to-task. Dismissals SHALL feed calibration (UC-26). Nothing
  reaches the client automatically.
- **AL8 — Cadence (default).** `Critical` = near-real-time push; everything else = a daily
  digest/brief; quiet hours respected. (Open: pure-pull dashboard vs. push.)
- **AL9 — UI unit.** Alerts surface in the **Action Center** (right drawer) as a categorised
  queue (tabs: All · Urgent · Clients · Market · Compliance · Tasks) with a bell badge and
  Mark-All-Read; the per-client **client-card** is the deep-dive view. See UI-5 (§17).

## 16. Message generation (deepens UC-5)

**Core principle — separate content from style.** The facts (numbers, instrument, swap,
mandate impact, rationale) are computed deterministically by the engine and *locked*. The
LLM only **renders** those locked facts in the client's voice — it is a translator, not an
author. This is what makes the draft trustworthy: it cannot fabricate a price or a
recommendation because it is given only a fixed fact sheet and told to use nothing else.

- **MSG1 — Style profile.** Each client SHALL have a style profile extracted from CRM notes
  along axes: analytical ↔ emotional, brief ↔ detailed, formal ↔ warm, data-first ↔
  values-first, risk-framed ↔ opportunity-framed; plus signature values and
  language/formality. The challenge's "data-driven" and "values-led" are the extreme
  presets. **Default: a continuous per-client profile**, with the two presets selectable.
- **MSG2 — Fact sheet (deterministic).** Message generation SHALL be fed a structured fact
  sheet: `{ trigger, holding, proposal, numbers, mandate_impact_unchanged,
  dna_points:[{value, source_note_id}], evidence:[{headline, url}] }`.
- **MSG3 — Render (LLM / Phoeniqs).** The LLM SHALL use ONLY the fact sheet, write in the
  style profile, cite evidence inline, and return `{draft, facts_used[]}`. Low temperature
  for fidelity; one call per drafted message (top alerts / on RM request).
- **MSG4 — Guardrail.** The output SHALL be validated: every number in the draft must appear
  in the fact sheet (no hallucination); the text is framed as a draft for discussion (no
  performance promises); the provenance map (claim → source) is attached.
- **MSG5 — Draft structure.** Personal opening → what happened (in their frame) → why it
  matters to *you* (DNA link) → recommendation (their style) → reassurance (mandate
  unchanged, E8) → their decision ("shall we discuss?"). A non-financial moment (UC-6)
  collapses to opening → why-it-matters → warm close, with no trade.
- **MSG6 — Register match (UC-13).** Tone SHALL match the moment: celebratory for a
  milestone, sober for a loss, reassuring in a panic — never a fixed template.
- **MSG7 — Always a draft (G1).** The RM edits/approves; the system SHALL NOT auto-send to
  the client.
- **MSG8 — Channel-awareness.** The suggested action SHALL include the right channel (call /
  email / in-person); emotional moments SHALL prefer a call over email.
- **MSG9 — Email handoff (demo scope).** The draft SHALL offer a one-click handoff ("Open as
  Outlook draft" / copy), so the RM sends from their **own** identity. The product is a
  companion, not a mail sender (G7).
- **MSG10 — Language.** English for the demo; German + formal address (Sie/Du, UC-19) is
  roadmap.
- **Roadmap (parked):** two-way Microsoft Graph / Outlook integration — send-from-RM with
  archiving. The product SHALL NOT auto-send email to clients even then.
- **Implemented (TASK-060):** **inbound** email ingestion via Microsoft Graph (read-only
  `Mail.Read`) is now a Change-Radar signal source. Each thread is classified by the local LLM
  into an instrument / client / book entity and fanned out by exposure exactly like a news or
  drift signal (§15). It is **read-only and optional** — disabled (a no-op) unless `MS_GRAPH_*`
  is configured. Outbound auto-send remains prohibited (G1/G7). See the §20 Azure exception.

## 17. UI & interaction model

The interface is a **command-driven, generative workbench**, not a fixed dashboard. The RM
*summons* views; the system *generates* them on demand. Two principles govern it: (a)
**human-in-the-loop** — every result ends in an explicit action the RM must take; (b)
**preference-driven, on-demand presentation** — the RM controls what they see and how.

**Layout.** App shell with a header (logo, 🔔 bell→Action Center, expand, avatar, theme),
a central **conversation canvas** (the transcript of generated widgets), a right-side
**Action Center** drawer (the §15 alert queue), and a bottom **input dock**.

- **UI-1 — Command canvas.** The input dock SHALL accept slash commands (`/client <name>`,
  `/stock <ticker>`, `/portfolio analysis`, `/create excel`, …), natural language, and
  **voice**. It SHALL offer scope tabs (All · Clients · Market ·
  Documents · Analysis), quick-command chips, and a "Hide input" focus mode.
- **UI-2 — Generative / on-demand rendering.** Views SHALL be generated in response to a
  command/NL/voice request and rendered into the transcript — there is no fixed panel
  layout. **Grounding:** the LLM selects *which widget + the narrative*; all numbers come
  from SIX / portfolio / CRM data — the UI SHALL NOT display fabricated figures (mirrors
  the §16 content/style separation).
- **UI-3 — RM view preferences ("view profile").** The RM SHALL be able to set how data is
  presented — chart vs. table, dense vs. narrative, default views, theme — and the same
  data SHALL render to that preference. (The RM-side mirror of the per-client style profile
  MSG1.)
- **UI-4 — Widget catalogue.** Generated widgets include: **Client Profile** card (portfolio
  value, YTD, last contact, financial goals with progress bars, recent activity);
  **Portfolio Analysis** (allocation donut, asset-class breakdown, top holdings, vs.
  benchmark); **Stock/Instrument** analysis; **Report/Excel** export; **Message draft +
  provenance panel** (§16). Every actionable widget SHALL carry contextual action buttons.
- **UI-5 — Action Center.** A right drawer presenting the §15 alert queue: bell badge,
  Mark-All-Read, category tabs (All · Urgent · Clients · Market · Compliance · Tasks), and
  alert cards with severity chip, client, due date, age, body, a primary + secondary action,
  and dismiss (×). Realises AL2–AL9.
- **UI-6 — Human-in-the-loop affordance (G1).** Every generated insight/alert SHALL end in
  explicit action buttons (Review · Approve · Rebalance · Prepare · Export); nothing
  executes without an RM click, and outward/irreversible actions (e.g. placing an order,
  sending a message) SHALL require confirmation.
- **UI-7 — Theming & accessibility.** Dark and light themes SHALL both be supported;
  contrast and readability follow accessibility norms (Visual Design criterion).
- **UI-8 — In-UI explainability (G2/G3).** Any generated view SHALL be expandable to show
  its sources (CRM note, news article, CIO view, SIX price) — the "why" travels with the
  widget.
- **UI-9 — Demo data.** The demo SHALL use the four real personas (Schneider, Huber, Räber,
  Ammann), not placeholder clients; the mockups' "Jane Appleseed" is illustrative only.

## 18. Canvas — our own generative UI (derived from data × use cases)

**Approach.** We build the generative UI ourselves (not a framework) as a typed **component
registry** + a thin render protocol. Widgets are not ad-hoc: each is a **view over a known
data entity**, serving a known use case. The "generative" goal is to **present the same
data entity in different ways on demand**, selected by the RM's command / NL / preference.

**Grounding (tool-as-component).** Each widget's props are produced by a data tool that
fetches real SIX / portfolio / CRM data; the LLM supplies only parameters (e.g. `clientId`,
`ticker`) and chooses/arranges widgets. The model never authors numbers (UI-2, §16).

### 18.1 Core data entities (the structures widgets present)
- **Source (from workbooks):** `Interaction` {date, medium, rmName, contact, note};
  `Position` {assetClass, subAssetClass, region, industryGroup, issuer, security, isin,
  targetCHF, currentCHF, valor, mic, yahoo}; `MandateStrategy` {subAssetClass → targetWeight};
  `CIORecommendation` {rating, ratingSince, …, industryGroup, isin, cioView, asOf};
  `Transaction`; `CashFlow`.
- **Derived (built by our system):**
  - `ClientDNA` {clientId, name, mandate, values[], exclusions[tag], tilts[tag],
    styleProfile, businessContext, family, lifeEvents[], promises[], temperament,
    sources[noteRef]}.
  - `EnrichedHolding` = Position + {tags(region/sector/value), livePrice, fitScore,
    conflicts[]}.
  - `PortfolioView` = holdings + {allocationBySubAssetClass, driftVsTarget(±2pp), fitAgg}.
  - `Alert` {client, class, actionType, severity, due, trigger, evidence[], why,
    suggestedAction, draftRef, confidence, status} (§15).
  - `SwapProposal` {holding, candidate, dnaReason, cioView, mandateNeutral, fitGain,
    sources}.
  - `Moment` {client, event, why, channel, draftRef, sources} (UC-6).
  - `MessageDraft` {clientId, factSheet, draftText, style, factsUsed[], provenance[],
    channel} (§16).
  - `NewsItem` {headline, source, url, time, sentiment, matchedHoldings[], matchedThemes[],
    impact} (§13).

### 18.2 View catalogue — the "different ways" per entity
- **ClientDNA** → DNA card · value-axis radar · relationship timeline (how values emerged
  from notes) · one-line "who they are".
- **PortfolioView** → allocation donut · holdings table · **drift bars** (vs ±2pp) · sector
  treemap · per-holding **fit heatmap** · conflicts list.
- **EnrichedHolding** → table row · detail card · price sparkline.
- **Alert** → Action-Center card · inline banner · list item (§15 / UI-5).
- **SwapProposal** → before→after card · side-by-side · mandate-neutral proof.
- **Moment** → moment card with suggested channel.
- **MessageDraft** → draft + provenance panel · **[data-driven ⇄ values-led] toggle** (same
  facts, two renders — the killer demo).
- **NewsItem** → feed item · impact badge · linked-to-holding chip.
- **Interaction** → timeline · relationship story.

### 18.3 Selection & rendering
- **V1.** A command / NL / voice request SHALL resolve to (entity instance + view variant),
  then render via `registry[component](validatedProps)`; unknown/invalid → fallback card.
- **V2.** The RM's **view preference** (UI-3) SHALL pick the default variant for an entity
  (e.g. portfolio as table vs donut) when the request doesn't specify one.
- **V3.** Each widget SHALL carry its data entity's `sources` for in-UI explainability
  (UI-8) and contextual RM action buttons (UI-6).

### 18.4 Use-case → view mapping (the four steps)
| Step (challenge) | Entities | Default views |
|---|---|---|
| 1. Build Client DNA (UC-1) | ClientDNA, Interaction | DNA card · value radar · relationship timeline |
| 2. Connect Portfolio & News (UC-2) | PortfolioView, EnrichedHolding, NewsItem | allocation donut/table · drift bars · news feed |
| 3. Surface Alerts (UC-3) | Alert, Moment, SwapProposal | Action-Center list · moment card · swap before→after |
| 4. Tailored Message (UC-5) | MessageDraft | draft + provenance · data-driven⇄values-led toggle |

## 19. Finalized core product (MVP scope)

The core product we will build, all under the global rules (human-in-the-loop G1,
traceability G2/G3, strategy preserved G4, CRM-companion G7):

1. **Generative, personalized UI** — RM summons views on demand; sets a **default view** for
   app entry; presents the same data in different ways (§17, §18).
2. **Personalized portfolio at scale** — DNA-driven, same-sector, CIO-constrained swaps with
   explainable fit scores across the whole book (§11, §12).
3. **News + CRM-driven alerts** — watchlist = held entities ∪ DNA themes; near-real-time
   monitoring; ranked, deduped alert queue (§13, §14, §15).
4. **Tailored message generation** — locked facts rendered in the client's style, with
   provenance and channel-awareness (§16).
5. **Voice mode** — query the canvas and **dictate notes** by voice (§19.1).
6. **Voice note & note generation** — dictation → structured CRM note written back, with DNA
   updates and follow-up tasks proposed (§19.1).
7. **Tasks with selective autonomous execution** — the agent generates tasks and
   **auto-runs the safe ones** (research / analysis / draft-prep), leaving all outward
   actions to the RM (§19.2).

### 19.1 Voice & note creation (new — UC-28)
- **VN1.** Voice input SHALL serve both querying the canvas and dictating notes.
- **VN2.** A dictated note SHALL be transcribed and structured into a CRM note
  {date, medium, contact, body}, presented as a **draft the RM approves** before it is
  written back to the CRM (G7).
- **VN3.** The system SHALL be able to generate a clean structured note from an interaction
  and propose **DNA updates** (new values / promises / life events) with their sources (G2).
- **VN4.** The system SHALL propose **follow-up tasks** extracted from the note.
- **Feasibility:** browser Web Speech API / a speech-to-text service for capture; Phoeniqs
  for transcription structuring and extraction. Demo-feasible.

### 19.2 Tasks & autonomous execution (new — UC-29)
- **TK1.** The system SHALL generate tasks from alerts (AL7), notes (VN4), and promises
  (UC-8); tasks appear in the Action Center **Tasks** tab.
- **TK2.** Every task SHALL carry an execution mode: **Auto** (agent executes) or **Manual**
  (RM executes).
- **TK3 — Autonomy boundary (G1).** Auto-executable tasks are limited to **read-only /
  analysis / research / draft-prep** that produce a *reviewable result* — e.g. research a
  topic, gather news, compute swap candidates, draft a summary. The agent SHALL NOT
  auto-execute **outward or irreversible** actions (contacting a client, placing an order,
  sending a message); those remain Manual.
- **TK4.** An autonomous **research** task SHALL run a research routine (web / news / SIX /
  CRM as appropriate) and return a **cited brief** into the canvas / task result (G2).
- **TK5.** Every auto-executed task SHALL log what it did and its sources, and be fully
  reviewable; its output is a draft/input for the RM, never an action taken on the client's
  behalf.
- **TK6.** Task lifecycle: created → (auto-run, or RM-triggered) → result → RM reviews →
  acts / closes.

## 20. Tech stack & deployment (decided)

**No Azure / no cloud dependency.** Everything runs locally and is self-hostable, packaged
with Docker Compose. (Overrides the Azure-shared-services path in the challenge's reference
diagrams.)

> **Scoped exception — Azure as email *transport* only (TASK-060).** Inbound email ingestion
> uses Microsoft Graph (Azure AD app registration, `Mail.Read`, client-credentials flow) purely
> as a **read-only email transport**, never as infrastructure. It is **optional and degrades to a
> no-op** when `MS_GRAPH_*` is unset, so the core stack stays fully local/self-hostable; no
> compute, LLM, storage, or database moves to Azure, and no email is ever auto-sent (G1/G7). This
> is the *only* Azure dependency in the product, and it is not required to run or demo the
> offline persona pipeline.

| Layer | Choice |
|---|---|
| Frontend | **React + Tailwind** (Vite) — our own component registry (§18) |
| Backend | **FastAPI** (Python) — replaces the demo's Express/TS reference |
| LLM | **Open-source, starting Gemma 3 12B** — local via Ollama, or hosted via **OpenRouter** when VRAM-limited (both OpenAI-compatible `/v1`) |
| Orchestration | FastAPI + **LangGraph** for orchestrator→domain agents; trust-critical flows stay deterministic |
| DB | **PostgreSQL + pgvector** |
| Cache / queue | **Redis** |
| Object store | **MinIO** (S3-compatible) |
| Dev infra | pgAdmin, MailHog (email-draft handoff testing, MSG9) |
| Packaging | **Docker Compose** |

- **ST1 — Provider abstraction.** LLM access SHALL go through one OpenAI-compatible interface
  so three backends are interchangeable by config (base URL + key + model id):
  (1) **Ollama** local (Gemma 3 12B) — fully private; (2) **OpenRouter** hosted open-source
  (e.g. `google/gemma-3-12b-it` / 27B) — for VRAM-limited dev/demo; (3) **Phoeniqs** —
  provided credits / fallback. The same open-source model family is used regardless of host.
- **ST1a — Privacy tier.** Only the Ollama path keeps data fully on-prem ("nothing leaves the
  bank"); OpenRouter and Phoeniqs are hosted. The architecture SHALL preserve the local path
  as the production/privacy option even when dev runs on OpenRouter.
- **ST2 — Small-model fit.** A 12B local model is sufficient *because* facts are computed
  deterministically (§16) and grounded via tool-as-component (§18): the LLM only writes prose
  and selects/arranges widgets, never computes numbers. Use constrained / JSON output + the
  existing validation guardrails to cope with weaker small-model tool-calling.
- **ST3 — Data stores.** Postgres (+pgvector) holds DNA, holdings, alerts, tasks, notes, and
  embeddings; Redis backs the news-poll + task queues and caching; MinIO stores reports/
  exports and voice-note audio.
- **ST4 — MCP connector.** A local MCP proxy connects to the **external** SIX MCP server;
  Event Registry is a REST client. (SIX/Tenity MCP servers remain external.)
- **ST5 — Agent mapping.** Orchestrator → LangGraph router; CRM Agent → DNA Builder;
  Portfolio Agent → Personalization Engine; News Agent → Watchlist Monitor; Message Agent →
  Message Generator; Dashboard + RM Interface Agent → generative UI + command layer.

### Docker Compose services
`frontend` (React/Vite) · `backend` (FastAPI) · `ollama` (Gemma 3 12B) · `postgres`
(+pgvector) · `redis` · `minio` · `pgadmin` · `mailhog` · `mcp-proxy`.

**Note:** the `demo/` folder (Express/TypeScript) stays as the *reference* for how to call
each provider; the product backend is rebuilt in FastAPI/Python.
