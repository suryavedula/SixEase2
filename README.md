# SixEase — The Next Generation of Wealth Advisory

> An advisor workbench that lets a relationship manager (RM) deliver hyper-personalised,
> *feel-known* service to every client at scale — with the human always in the loop.
>
> Built for **SwissHacks 2026**, the SIX × Noumena Digital × NTT DATA challenge
> *"The Next Generation of Wealth Advisory."*

## What it is

The best relationship managers know their clients inside out — values, life events, business
context shape every proposal. That care doesn't scale past a handful of clients. **SixEase**
closes the gap: the AI remembers everything so the human can show up as if they remembered
everything. AI suggests and explains, the RM recommends, the client always decides.

SixEase is a **companion layer on top of the existing CRM — not a CRM replacement.** It reads
the bank's conversation logs, builds a structured "investment identity" (DNA) for each client,
watches portfolios against live news and CIO signals, and turns every insight into a
*reviewable draft action* for the RM.

The core mechanic: **strategy is invariant, instrument selection is the free variable.** The
mandate (Defensive / Balanced / Growth) and the CIO sub-asset-class targets are never changed.
Personalisation happens only by swapping *which instrument* fills a slot — a same–`Industry
Group`, CIO-`BUY`, not-currently-held, risk-neutral replacement that better fits the client's
DNA. That's what makes personalisation-at-scale possible without breaking the mandate.

## Core features (MVP)

1. **Generative, personalised UI** — the RM summons views on demand and sets a default entry
   view; the same data is presented in different ways. A typed component registry + a render
   protocol where the model emits `{component, props}` and the client renders it. Grounding
   rule: the LLM picks/arranges widgets and writes narrative, but **every number comes from a
   data tool — it never authors figures.**
2. **Personalised portfolio at scale** — DNA-driven, same-sector, CIO-constrained instrument
   swaps with explainable fit scores across the whole book.
3. **News + CRM-driven alerts** — watchlist = held entities ∪ DNA themes; near-real-time
   monitoring via Event Registry; a ranked, deduped alert queue.
4. **Tailored message generation** — locked facts rendered in each client's preferred style
   (analytical/data-driven vs. values-led/inspiring), with provenance and channel-awareness.
5. **Voice mode** — query the canvas and dictate notes by voice (local Whisper STT).
6. **Voice-note & note generation** — dictation → structured CRM note written back as a draft,
   with proposed DNA updates and follow-up tasks.
7. **Tasks with selective autonomous execution** — the agent generates tasks and **auto-runs
   the safe ones** (research / analysis / draft-prep) into cited briefs, leaving every outward
   or irreversible action to the RM.

### Non-negotiable principles

- **Human in the loop** — nothing reaches the client automatically. Agents may research and
  draft autonomously, but never take outward/irreversible actions (contacting a client,
  placing an order, sending a message).
- **Traceability & explainability** — every alert, suggestion, and drafted message cites its
  evidence (the CRM note, portfolio position, news event, or CIO row that produced it) and
  states *why* in plain language.
- **Strategy preserved** — the mandate and CIO targets are never altered; only instrument
  selection within a slot changes.

## Architecture

| Layer | Choice |
|---|---|
| Frontend | **React 19 + Tailwind v4** (Vite) — our own generative component registry |
| Backend | **FastAPI** (Python) |
| Orchestration | **LangGraph** — orchestrator → CRM / Portfolio / News / Message agents; trust-critical flows stay deterministic |
| LLM | Open-source, **Gemma 3 12B** local via **Ollama** (default), or hosted via **OpenRouter** / **Phoeniqs** — one OpenAI-compatible interface, switchable by config |
| Embeddings | Always **Ollama** (dedicated client) |
| Speech-to-text | Local **faster-whisper** (GPU), OpenAI-compatible |
| Database | **PostgreSQL + pgvector** (DNA, holdings, alerts, tasks, notes, embeddings) |
| Cache / queue | **Redis** (news-poll + task queues, caching) |
| Object store | **MinIO** (S3-compatible — reports, exports, voice-note audio) |
| Dev infra | pgAdmin, MailHog (email-draft handoff testing) |
| Packaging | **Docker Compose** |

**No Azure / no cloud dependency** — everything runs locally and is self-hostable. (Optional,
degrades to a no-op: Microsoft Graph as a *read-only* email-ingestion transport when
`MS_GRAPH_*` is configured; no compute, LLM, storage, or DB ever moves to the cloud, and no
email is ever auto-sent.)

### External providers

- **SIX Financial Data** — an **MCP server** (JSON-RPC `tools/call` over streamable-http),
  not REST. Address instruments by **Valor**, listings by composite **`{valor}_{mic}`** for
  price tools, and bonds by **ISIN** via `instrument_symbology`. See `docs/SIX_MCP.md`.
- **Event Registry / newsapi.ai** — live news + sentiment, REST; near-real-time minute-stream
  for 24/7 monitoring.
- **Phoeniqs** — OpenAI-compatible hosted LLM credits (fallback to the local Ollama path).

## Project structure

```
backend/         FastAPI app — agents (LangGraph), loaders (DNA, swap, alerts, news…),
                 routers, models (Postgres + pgvector), SIX/news/LLM clients
frontend/        React + Vite + Tailwind — generative UI shell, widget registry, API clients
data/            The two provided workbooks (SwissHacks CRM + Portfolio Construction)
docs/            Requirements.md (living product spec, §1–§20) + vendor references
demo/            Reference integration (Express/TS) — how to call each provider; NOT the product
infra/           Postgres init (pgvector), local infra config
docker-compose.yml
```

## Getting started

Prerequisites: Docker + Docker Compose. A CUDA GPU is recommended for the local Ollama and
Whisper services (the LLM/STT paths can be pointed at hosted providers instead via `.env`).

```bash
cp .env.example .env          # fill in SIX_MCP_TOKEN, NEWSAPI_KEY, and (optionally) PHOENIQS_API_KEY
docker compose up -d          # starts the full stack; backend runs alembic migrations on boot
```

Pull the local model once (first run):

```bash
docker compose exec ollama ollama pull gemma3:12b
docker compose exec ollama ollama pull <your OLLAMA_EMBED_MODEL>
```

Then open:

| Service | URL |
|---|---|
| Frontend (workbench) | http://localhost:5173 |
| Backend API + docs | http://localhost:8000 · http://localhost:8000/docs |
| MailHog (draft email inbox) | http://localhost:8025 |
| MinIO console | http://localhost:9001 |
| pgAdmin | http://localhost:5050 |

### Configuration notes

- **LLM provider** is selected by `LLM_PROVIDER` (`ollama` default; `openrouter` or `phoeniqs`
  when VRAM-limited). All three are OpenAI-compatible and interchangeable by config.
- **Embeddings always use Ollama** regardless of the active chat provider.
- **Speech-to-text** runs locally via the `whisper` service (`WHISPER_PROVIDER=local`).
- Ports, credentials, and provider keys are all driven from `.env` — see `.env.example` for
  the full annotated list.

## The four personas

The challenge ships four client personas, each with a distinct trigger event:

| Persona | Profile | Strategy | Trigger |
|---|---|---|---|
| **Schneider** — The Personal Connection | Emotional, purpose-driven; family foundation funding chronic-illness research | Balanced | Pharma company shuts down research for that disease |
| **Huber** — The Purpose-Driven Investor | Environmentalist financing reforestation; holds consumer staples | Defensive | Consumer-goods firm announces a historic palm-oil deforestation cut-off |
| **Räber** — The Defensive Value Investor | Conservative Swiss couple; precision-engineering background; averse to US tech | Defensive | CIO suggests rebalancing blue chips into US AI stocks |
| **Ammann** — The Corporate Reputation Case | Prominent Swiss entrepreneur; reputational risk = financial risk | Growth | Labour-exploitation scandal hits a portfolio consumer brand |

## Data

Two workbooks in `data/` drive everything (amounts in CHF; dates are Excel serials; bonds
priced at par; sub-asset-class drift rule is **±2.0pp**, with Balanced & Growth shipping
deliberate breaches):

- `SwissHacks CRM.xlsx` — one tab per persona; a 3-year narrative of RM interactions. Client
  identity is *extracted* from notes, not read off fields.
- `SwissHacks Portfolio Construction.xlsx` — model mandates, CIO sub-asset-class targets, the
  172-row CIO recommendation list (BUY/HOLD/SELL + swap candidates), and the three sample
  portfolios with SIX (Valor + MIC) / ISIN / Yahoo identifiers.

Full inspected contents and conventions: `docs/Requirements.md` §10.

## Documentation

- **`docs/Requirements.md`** — the living product spec (§1–§20): vision, engine model, data
  inventory, and every design decision. **Start here.**
- `Project-Overview.html` — self-contained visual explainer + interactive mock prototype
  (open in a browser, no server needed).
- `docs/SIX_MCP.md` — tested reference for the SIX MCP tools with real example outputs.
- `docs/Phoeniqs_AI.md` — Phoeniqs access & setup.
- `demo/` — reference integration that smoke-tests all three providers end to end.

## Reference demo

The `demo/` folder wires Phoeniqs LLM, the SIX MCP server, and Event Registry behind a
TypeScript/Express backend — kept as a credential smoke-test and a reference for how to call
each provider. It is **not** the product.

```bash
cd demo && cp .env.example .env   # fill PHOENIQS_API_KEY, SIX_MCP_TOKEN, NEWSAPI_KEY
npm install && npm run dev        # http://localhost:3000
```

`GET /api/analysis/integrations` pings all three providers with masked credentials — use it to
verify keys before building.
