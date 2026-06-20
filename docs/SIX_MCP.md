# SIX Financial Data API (MCP) — what you can pull, and how

This is a practical, **tested** guide to the SIX MCP server shipped with this
repo via `mcp.json`. Every capability and example output below was verified
live against the server with the hackathon bearer token on **2026-06-09**.
Where a tool is *not* reachable with this token, it says so explicitly — that
distinction matters, so don't assume a tool works just because it's listed.

> **Server:** `streamable-http` MCP, 23 tools over a SIX GraphQL backend.
> The URL + bearer token are provided by the SIX Group contact (see the main
> README, "Available Technology"). Put them in an `mcp.json` and drop that file
> into Claude Code / Copilot / any MCP client to get these tools in your agent.

---

## TL;DR

- **What it is:** an authoritative reference-and-market-data API for financial
  instruments — identity, cross-identifiers, listings/venues, issuers, and
  prices (end-of-day + intraday). You look an instrument up once and get its
  canonical SIX **Valor**, ISIN, and every other code (CUSIP, SEDOL, WKN,
  FIGI, ticker), the venues it trades on, the legal entity behind it, and its
  price history.
- **How you address things:** instruments by **Valor**; listings (instrument
  *on a venue*) by the composite **`{valor}_{mic}`** (e.g. `645156_XNAS`);
  bulk lookups by **ISIN / VALOR / CUSIP** via `scheme`.
- **Coverage:** a global multi-asset universe — **27 instrument types**
  (equities, bonds, funds, derivatives, structured products, FX, indices, …),
  millions of listings across world venues. Full taxonomy in §5.
- **With *this* token:** **17 of 23 tools work.** Reference data, symbology,
  listings, venues, entities, and all pricing are available. **6 tools are
  permission-gated** (fundamentals, estimates, both classification tools,
  instrument detail/term-sheet, Swiss stamp duty) — see §4.

---

## 1. The mental model

```
Entity (issuer, e.g. "Amazon.com Inc", LEI ZXTILKJKG63JELOEG630)
  └─ Instrument  (Valor 645156, ISIN US0231351067, type EQUITY)
       ├─ Symbology   (CUSIP 023135106, SEDOL 2000019, WKN 906866, ticker …)
       └─ Listing(s)  (the instrument *on a venue*)
            645156_XNAS  (NASDAQ, USD)   ← most-liquid market
            645156_XSWX  (SIX Swiss, …)
            645156_XFRA  (Frankfurt, …)
                 └─ Market data: end-of-day + intraday prices
```

Two ID conventions, and getting them right is 90% of using the API:

| You have | You want | Tool family | ID form |
|---|---|---|---|
| A name / fuzzy text | The instrument | `find_instrument` | text → returns Valor + ISIN |
| A Valor | Reference / symbology / venues | `instrument_*`, `entity_base` | `valors: ["645156"]` |
| A Valor **and** a venue | Listing data / prices | `listing_*`, `*_snapshot`, `*_history`, `market_base` | `listing_ids: ["645156_XNAS"]` |
| A pile of ISINs/CUSIPs | Their instruments, batched | `execute_graphql` | `instruments(ids: [...], scheme: ISIN)` |
| Filter criteria | A set of instruments | `criteria_search` | `criteria: {...}` |

**Convention for the data tools:** call with `mode: "describe"` first to see the
GraphQL path + available fields for that type, then `mode: "execute"` with your
`fields`. If you pass a field the type doesn't have, the server replies with the
**exact list of valid fields** — cheap, fast schema discovery.

---

## 2. What you can pull (the 17 accessible tools)

All outputs below are **real responses** from the live server.

### Find an instrument from text — `find_instrument`
```
find_instrument("Amazon")
→ isin=US0231351067  name="Amazon.Com Rg"  type=EQUITY  valor=645156  mic=XNAS
```
Free-text / fuzzy search, ranked by SIX score. The entry point when you don't
yet have an identifier.

### Filter the universe by criteria — `criteria_search`
```
criteria_search(target="instruments",
                criteria={instrumentType:["EQUITY"], issuerCountry:["CH"],
                          instrumentStatus:"ACTIVE"}, size=5)
→ CH0000002193  Laiterie Modele N
  CH0000005816  BALKO N
  CH0000031127  Helvetic Person I
  CH0000041795  White Arena Rg
  CH0000043064  Ifosa N
```
Structured screening (by type, country, status, …). Returns matching
instruments; page with `size`.

### Reference data — `instrument_base`
```
instrument_base(valor=645156, fields=[isin,instrumentShortName,instrumentType,…])
→ isin=US0231351067  name="Amazon.Com Rg"  type=EQUITY
  issuer="Amazon.com"  LEI=ZXTILKJKG63JELOEG630  mic=XNAS
```
This is also where **bond terms** live (no permission needed):
```
instrument_base(valor=12718119, fields=[isin,instrumentShortName,instrumentType,
                currentCouponRate,currentCouponType,maturityDate,nominalCurrency])
→ CH0127181193  "1.25 EIDG 37"  BOND
  currentCouponRate=1.25  currentCouponType=FIXED
  maturityDate=2037-06-27  nominalCurrency=CHF
```

### All identifiers — `instrument_symbology` / `listing_symbology`
```
instrument_symbology(valor=645156)
→ CUSIP=023135106  SEDOL=2000019  WKN=906866
```
`listing_symbology` adds venue-level codes: `ticker, sedol, figi, bbgTicker,
sixSymbol, listingSymbol, occOptionSymbol, …`. This is your **identifier
cross-walk** — ISIN/Valor ⇄ CUSIP/SEDOL/WKN/FIGI/ticker.

### Where it trades — `instrument_markets`
```
instrument_markets(valor=645156)
→ listings on XNAS (MOST_LIQUID_MARKET), XSWX, XFRA, XMEX, …
```
Enumerates every venue an instrument lists on, flagging the most-liquid market —
this is how you pick the right `{valor}_{mic}` for pricing.

### The listing itself — `listing_base`
```
listing_base(listing_id="645156_XNAS")
→ ticker=AMZN  listingCurrency=USD  tradingStatus=TRADED  priceQuoteType=PRICE_IN_UNITS
```

### The venue — `market_base`
```
market_base(listing_id="645156_XNAS", fields=[mic,marketLongName,marketCountry,marketTimeZone])
→ XNAS  NASDAQ  US  America/New_York
```
Venue reference: long name, country, timezone, open/close times, trading days.

### The issuer — `entity_base`
```
entity_base(valor=645156, fields=[lei,entityLongName,entityType,entityCountry])
→ lei=ZXTILKJKG63JELOEG630  "Amazon.com Inc"  COMPANY  US
```
Legal-entity reference: LEI, legal name, type, domicile country, status.

### Prices — end of day — `end_of_day_snapshot` / `end_of_day_history`
```
end_of_day_snapshot(listing_id="645156_XNAS")
→ close=245.22 (2026-06-08)  volume=12.75M  P/E=29.33
  marketCap=$2.64T  histVol30d=28.03

end_of_day_history(listing_id="645156_XNAS")
→ daily OHLCV time series   (e.g. 2026-05-28 close=274.00)
```
EOD snapshot carries valuation extras (P/E, market cap, historical vol).
`end_of_day_history` is the daily OHLCV series — **this is the tool to migrate
the price layer onto** if you want the dataset 100% SIX-sourced.

### Prices — intraday — `intraday_snapshot` / `intraday_history`
```
intraday_snapshot(listing_id="645156_XNAS")
→ last=245.22  volume=12,754,186

intraday_history(listing_id="645156_XNAS", sub_type="summary")
→ interval OHLCV bars  (open, high, low, last, volume, numberOfTrades)
```
`sub_type` is `summary` (interval bars) or `trades` (tick level).

### Raw GraphQL — `execute_graphql`
The escape hatch. Anything the typed tools don't shape, you can query directly.
The repo uses it to **batch-resolve ISINs → Valor/MIC** in one round-trip:
```graphql
query($ids:[UserInputId!]!){
  instruments(ids:$ids, scheme:ISIN){            # scheme ∈ ISIN | VALOR | CUSIP
    referenceData{ instrumentInfo{ valorNumber } }
    marketData{ … }
  }
}
```
(Note the variable type is `[UserInputId!]!`, *not* `[ID!]!`.)

### Utility — `get_datetime`, `search_schema`, `describe_type`
```
get_datetime()              → 2026-06-09 18:40:00   (server clock / as-of)
search_schema(keyword=…)    → find schema types/fields by keyword
describe_type("…")          → full field list for a GraphQL type
```
Introspection: when you don't know the field name, `search_schema` /
`describe_type` (or just send a wrong field and read the "Available:" list).

---

## 3. Cheat-sheet: question → tool

| You want to know… | Tool |
|---|---|
| "What's the Valor/ISIN for *X*?" | `find_instrument` |
| "Give me every Swiss active equity" | `criteria_search` |
| "CUSIP / SEDOL / WKN / FIGI for this?" | `instrument_symbology`, `listing_symbology` |
| "Coupon, maturity, currency of this bond?" | `instrument_base` |
| "Which exchanges does it trade on?" | `instrument_markets` |
| "Ticker & currency on NASDAQ?" | `listing_base` |
| "What/where is venue XNAS?" | `market_base` |
| "Who's the issuer? LEI?" | `entity_base` |
| "Yesterday's close / 1y of daily prices?" | `end_of_day_snapshot`, `end_of_day_history` |
| "Live-ish last price / intraday bars?" | `intraday_snapshot`, `intraday_history` |
| "Resolve 140 ISINs at once" | `execute_graphql` |

---

## 4. What this token CANNOT do (permission-gated)

SIX gates tools by **function id** tied to the token's entitlements. With the
hackathon token, **6 of 23 tools** return
`User does not have access to '<tool>'. Required function id: 'NN'.` — verified
live, not assumed:

| Tool | Function id | What you'd lose |
|---|---|---|
| `fundamentals` | 82 | Balance-sheet / income-statement financials |
| `estimates` | 81 | Analyst estimates & recommendations |
| `instrument_detail` | 85 | Extended term sheets (e.g. full bond detail) |
| `instrument_classification` | 85 | Sector/asset classification (e.g. GICS) on instruments |
| `entity_classification` | 85 | Sector/industry classification on issuers |
| `swiss_stamp_duty` | 755 | Swiss transaction stamp-duty flags |

**Practical impact for this project: none.** Everything the pipeline needs —
identity, symbology, venues, issuer, and prices — is in the 17 accessible
tools. Bond coupon/maturity come from `instrument_base` (accessible), not the
gated `instrument_detail`. If you genuinely need fundamentals, estimates, or
classification, ask the SIX contact to add those function ids to the token.

---

## 5. The universe of instruments (27 types)

`criteria_search` / `instrument_base` expose SIX's full multi-asset taxonomy.
The `instrumentType` enum has **27 values**:

```
EQUITY                  BOND                    FRN
CONVERTIBLE_BOND        MTN                     MONEY_MARKET_INSTRUMENT
STRUCTURED_PRODUCT      LEVERAGED_PRODUCT       OPTION
FUTURE                  ETD                     FORWARD_TRANSACTION
COMBINED_TRANSACTION    INDEX                   COMMODITY
CURRENCY                TECHNICAL_CURRENCY      INTEREST_RATE
REPO                    REPO_BASKET             RIGHT
INSURANCE_POLICY        SAVINGS_BOOK            TRUST_SHARE
TRUST_CERT_SHARE        TRUST_CERT_FOUNDATION   OTHER
```

Roughly grouped:

- **Equity-like:** `EQUITY`, `RIGHT`, `TRUST_SHARE`, `TRUST_CERT_SHARE`,
  `TRUST_CERT_FOUNDATION` (funds/trusts surface here and via `criteria_search`).
- **Fixed income:** `BOND`, `CONVERTIBLE_BOND`, `FRN` (floating-rate),
  `MTN`, `MONEY_MARKET_INSTRUMENT`.
- **Derivatives:** `OPTION`, `FUTURE`, `ETD` (exchange-traded derivative),
  `FORWARD_TRANSACTION`, `COMBINED_TRANSACTION`.
- **Structured / leverage:** `STRUCTURED_PRODUCT`, `LEVERAGED_PRODUCT`.
- **Macro / reference:** `INDEX`, `COMMODITY`, `CURRENCY`,
  `TECHNICAL_CURRENCY`, `INTEREST_RATE`.
- **Financing / other:** `REPO`, `REPO_BASKET`, `INSURANCE_POLICY`,
  `SAVINGS_BOOK`, `OTHER`.

For this hackathon's portfolios you'll mostly touch `EQUITY` and `BOND`, with
`CURRENCY` for FX and `INDEX` for benchmarks — but the API reaches the whole
list above.

---

## 6. Gotchas worth knowing

- **Two ID shapes.** Instrument tools take `valors: ["645156"]`. Listing /
  price / venue tools take `listing_ids: ["645156_XNAS"]`. Mixing them up is
  the #1 error. (`market_base` and `swiss_stamp_duty` take `listing_ids`, not
  `mics`/`valors` — surprising but true.)
- **`describe` before `execute`.** Field names are type-specific; a wrong field
  returns the valid list, so use that as live documentation.
- **`scheme` for bulk.** `execute_graphql`'s `instruments(ids, scheme:)` accepts
  `ISIN`, `VALOR`, `CUSIP` — batch hundreds in one call; variable type is
  `[UserInputId!]!`.
- **Permission errors are explicit.** A gated tool says exactly which function
  id it needs — you'll never silently get empty data from a missing
  entitlement; you get a clear error (see §4).
- **As-of clock.** `get_datetime` returns the server's reference time; EOD
  snapshots lag one settled trading day (e.g. on 2026-06-09 the snapshot close
  was dated 2026-06-08).

---

*Verified live on 2026-06-09 against the hackathon token. If the token's
entitlements change, re-run the relevant tool — §4 is the only part that
depends on the token, the rest is the server's fixed capability surface.*
