# SIX-Noumena-NTT-Data

## Challenge Title

**The Next Generation of Wealth Advisory**

## Introduction

### Problem Description

Hyper-personalised wealth advice is today reserved for a handful of ultra-high-net-worth clients. The best relationship managers know their UHNWI clients inside out — values, life events, and business context shape every proposal — but this level of care does not scale past a handful of clients. Tailoring proposals to each client's full personal context, monitoring news across every holding, and drafting individual narratives takes more time than any relationship manager has.

AI changes the equation. With the right workbench, every client receives the same proactive, hyper-personalised care — 24/7 — while the relationship manager stays in the loop and the client always decides.

### Case Introduction

The task is to build the next-generation advisor dashboard in 48 hours: a single place where a relationship manager can understand a client's investment identity, monitor their portfolio against live news and CIO signals, and act on the right insight at the right time.

The core insight is that the investment strategy stays unchanged. Personalisation happens at the asset level: within a client's chosen mandate (Defensive, Balanced, or Growth), AI identifies holdings that conflict with the client's personal DNA and proposes a replacement from the same sector that fits both the strategy and the client personally.

The dashboard is built around four steps:

1. **Read and Interpret CRM Notes** — parse raw conversation logs and build each client's investment identity: values, business context, and personal priorities.
2. **Connect to Portfolio and News** — link the client profile to their current holdings and a live news feed.
3. **Surface Relevant Alerts** — match each client's profile against the portfolio and incoming news to flag potential conflicts or opportunities.
4. **Generate a Tailored Message** — draft the RM's advisory note in the client's preferred style: data-driven and precise, or values-led and inspiring.

**Human in the loop:** AI equips the relationship manager with insights and draft proposals. It never advises the client directly. The RM recommends, the client always decides and places the orders.

One suggested architecture is a multi-agent approach — an orchestrator coordinating a CRM Agent, Portfolio Agent, News Agent, and Message Agent, with a consolidated dashboard — but teams are free to innovate.

## Potential Users

Relationship managers in wealth management who act as trusted partners in helping high-net-worth and ultra-high-net-worth clients grow and protect their wealth.

## Use Cases

The solution brings together four core capabilities:

- **Build the Client DNA:** AI reads all raw CRM conversation logs and maps each client's personal profile — values, business interests, family context, and individual preferences — automatically, without manual data entry.
- **Monitor Global News 24/7:** News relevant to a client's holdings or personal profile is flagged the moment it breaks: a pharma pivot, a governance scandal, a sustainability milestone.
- **Suggest Personal Asset Swaps Within the Strategy:** Within the client's existing mandate, AI identifies holdings that conflict with their DNA and proposes a replacement from the same sector that fits both the strategy and the client personally. The CIO recommendation list constrains the swap universe.
- **Personalise the Advisory Message:** Every proposal comes with a draft message for the RM, written in the client's preferred communication style — analytical and data-driven for one, purpose-led and inspiring for another.

The challenge provides four client personas to build and test against, each with a distinct trigger event:

| Persona | Profile | Strategy | CRM Tab | Portfolio Tab | Trigger |
|---|---|---|---|---|---|
| Schneider — The Personal Connection | Emotional and purpose-driven; family foundation supporting a specific chronic-illness research field | Balanced | `CRM Schneider` | `Sample Portfolio Balanced` | Pharma company shuts down its research division for that disease |
| Huber — The Purpose-Driven Investor | Environmentalist financing South American reforestation; holds global consumer staples | Defensive | `CRM Huber` | `Sample Portfolio Defensive` | Consumer goods company announces historic palm oil deforestation cut-off |
| Räber — The Defensive Value Investor | Conservative Swiss couple; precision-engineering background; averse to US tech | Defensive | `CRM Raeber` | `Sample Portfolio Defensive` | CIO suggests rebalancing from blue chips into US AI stocks |
| Ammann — The Corporate Reputation Case | Prominent Swiss entrepreneur; reputational risk equals financial risk | Growth | `CRM Ammann` | `Sample Portfolio Growth` | Labour exploitation scandal hits a consumer brand in the portfolio |

## Expected Outcome

Expected deliverables include an end-to-end clickable prototype or working front-end; a minimal back-end or agent flow demonstrating personalisation and reasoning; and a short demo story showing how a relationship manager uses the dashboard to understand a client change, explain it, and decide on the next best action.

Expected Presentation: A concise presentation (.pptx) including slides with a clear demo of the developed solution.
Key elements:
-   Problem & solution: Clearly define the problem and how your solution addresses it
-   Demo: Showcase the solution in action within the slides
-   Core functionalities: Highlight key features and their value
-   User journey: Illustrate how users interact with the solution

Each hack team is required to **submit their code**; and **complete a short feedback** form on the MCP (what worked, what didn’t, etc.), one submission per team is sufficient and it will take no more than 5 minutes: https://forms.office.com/e/tX2cH5n9Yi 

## Technology

### Available Technology

- **SIX Financial Information (MCP server + Web API):** market and financial data including real-time and historical prices (equities, funds, ETFs, bonds), macroeconomic indicators (rates, inflation, FX), fundamentals, and estimates. The MCP server exposes 23 tools (reference data, symbology, venues, issuers, prices); 6 tools are outside the hackathon token's subscription. Configure via `mcp.json` (streamable-http, bearer token provided by the SIX Group contact) — the same file configures both the data pipeline and any participant's tooling. Each sample-portfolio position carries a Valor and MIC (combine as `{Valor}_{MIC}` for SIX MCP listing tools such as `end_of_day_snapshot`, `intraday_snapshot`, `end_of_day_history`; use the Valor alone for instrument tools). For bonds, use SIX `instrument_symbology` with the ISIN directly.
- **Event Registry / Tenity MCP-News Server:** live news and sentiment feed for event- and news-driven signals. [Event Registry API](https://newsapi.ai/) access is provided; Yahoo Finance and Google News also work.
- **LLM API Credits:** credits for large language model APIs are provided via [Phoeniqs](https://console.phoeniqs.com/) — no need to bring your own key.
- **Provided datasets (two workbooks):**

| Workbook | Contents |
|---|---|
| `data/SwissHacks CRM.xlsx` | Three-year relationship-manager interaction logs for four sample clients (Räber, Schneider, Huber, Ammann), capturing financial behaviour, preferences, and evolving signals over time. One tab per client. |
| `data/SwissHacks Portfolio Construction.xlsx` | Three model mandates (Defensive, Balanced, Growth; each summing to CHF 10M): CIO sub-asset-class targets (`Portfolio Strategies`), current positions with target and drifted market values, a CIO recommendation list with BUY/HOLD/SELL ratings and swap candidates, three-year transaction history, and cash flows (deposits, withdrawals, fees, coupons). Includes SIX (Valor + MIC) and Yahoo ticker identifiers. The Balanced and Growth portfolios carry deliberate post-rebalance mandate-drift breaches for use in rebalancing scenarios. |

- **Noumena Digital:** domain models, knowledge graphs, and AI-ready financial abstractions.
- **NTT DATA:** reference architectures and AI / cloud / trust-by-design assets, including Azure OpenAI–based patterns for explainable AI, retrieval-augmented generation, and multi-agent decision support.

### Expected or Suggested Tech Stack

SIX MCP server (streamable-http, bearer token) with the SIX Web API as a REST/JSON alternative (certificate-based authentication); Event Registry API or Tenity MCP-News server for news signals; LLM API of your choice (credits provided); Noumena Cloud (Azure-based) with knowledge graphs and financial abstractions; and Azure OpenAI–based patterns for explainable AI, retrieval-augmented generation, and multi-agent decision support.

## Challenge Slides

- [The Next Generation of Wealth Advisory — challenge pitch deck](docs/The%20Next%20Generation%20of%20Wealth%20Advisory.pdf)
- [The Next Generation of Wealth Advisory — deep-dive deck](docs/The%20Next%20Generation%20of%20Wealth%20Advisory%20DeepDive.pdf)

## Resources & Further Information

### Reference Integration Demo

The [`demo/`](demo/) folder contains a runnable starter that wires the three core integrations together end to end — Phoeniqs LLM, the SIX MCP server, and Event Registry news — behind a TypeScript/Express back-end and a single-page front-end. It exposes a stock-analysis endpoint (`POST /api/analysis/analyze`) and an integration health check (`GET /api/analysis/integrations`), so you can confirm your credentials work before building on top.

- **Setup:** copy `demo/.env.example` to `demo/.env` and fill in your Phoeniqs, SIX MCP, and Event Registry keys.
- **Run:** `cd demo && npm install && npm run dev`, then open `http://localhost:3000`.

Use it as a reference for how to call each provider, or as scaffolding for your own dashboard.

### Relevant Links

- SIX Financial Information MCP tools reference: see `docs/SIX_MCP.md` for a tested guide to all 23 tools with real example outputs.
- News aggregation API (used by the Tenity MCP-News server): https://newsapi.ai/
- LLM API platform (Phoeniqs): https://console.phoeniqs.com/
- Phoeniqs setup guide (access + OpenCode config): [Phoeniqs AI — Access & Setup](docs/Phoeniqs_AI.md)
- SIX MCP Developer Guide (vendor reference): [MCP Developer Guide 2026](docs/MCP%20Developer%20Guide%202026.pdf)

### Additional Information

Data conventions for the portfolio workbook: all amounts are in CHF; ISINs follow ISO 6166; equities are priced at real historical closes and bonds at par (100% of face value); for bonds, quantity = face value ÷ 100. Summing BUY − SELL quantities per ISIN gives the current position. `Current (CHF)` reflects post-rebalance market drift (prices as of approximately 10 days after the April 2026 rebalance); `Target (CHF)` is the rebalance allocation and still sums to CHF 10,000,000 per portfolio. The workbook README sheet lists SIX coverage details and the ±2.0pp mandate-drift rule.

## Judging Criteria

| Criterion | Description | Weight |
|---|---|---|
| Creativity | Novel human–AI interaction; fresh ideas beyond standard chatbots | 25% |
| Trust & Explainability | Transparency, traceability, and human control | 25% |
| Feasibility | Technical realism and architectural soundness | 20% |
| Visual Design | Clarity, usability, and a trust-oriented UI | 15% |
| Presentation Quality | Clear and convincing storytelling | 15% |

## Point of Contact

### Contact Person(s)

| Company | Name | Contact | Support |
|---|---|---|---|
| SIX | Ramiro Lopez Cento | ramiro.lopez@six-group.com | MCP |
| SIX | Laurent Lefevre | laurent.lefevre@six-group.com | webAPI, MCP |
| SIX | Jennifer Chang | jennifer.chang@six-group.com | Coordination |
| SIX | Magdalena Tuta | magdalena.tuta@six-group.com | Coordination, Pitch Training |
| NTT DATA | Thomas Geiger | thomas.geiger@nttdata.com | Wealth Management Expert, Personas, Business Case |
| NTT DATA / Phoeniqs | Stefan Taroni | stefan.taroni@phoenix-technologies.ch | Tech / LLM Infrastructure & Credits |
| Noumena Digital | Sandra Daub | sandra@noumenadigital.com | Wealth Management Expert, Personas, Business Case |
| Noumena Digital | Imants Firsts | imants.firsts@noumenadigital.com | Tech Infrastructure |

### Availability

In person throughout the event (SwissHacks, Zurich, 19 to 21 June 2026). Mentors will be on-site on the evening of 19 June after the presentations, and on 20 June throughout the day. The contacts above are also reachable by email for any questions during the event.

## Prize

Thank you for choosing the SIX challenge!

The top two teams will receive the opportunity to pitch to SIX Management + receive SIX Goodie Bags ;-)

Plus — all our hackers have the chance to receive a private pitch coaching session with our expert on Saturday, in preparation to the Sunday evaluations. Sign up with Magdalena at the SIX Booth!

