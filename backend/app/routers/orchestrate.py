"""Conversational orchestrator (TASK-043, EPIC-13).

The bottom-dock chat endpoint. Turns a free-text / natural-language query into a
conversational reply *plus* a set of generative-UI widgets, grounded on the
client's real data.

Design (matches the product's generative-UI contract):
  - The LLM writes the narrative reply and *picks/arranges* widgets by name.
  - It never authors figures: every number lives inside a widget, which fetches
    it from a data tool. The model only emits `{component, props}`.
  - The server resolves which client is in focus and injects the client_id into
    each client-scoped widget, so the model never handles UUIDs.

Degrades gracefully: if the LLM is unreachable, returns a plain reply and a
best-effort widget derived from the query so the dock still responds.
"""

import re
import uuid
from difflib import SequenceMatcher
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.llm import json_chat
from app.logging import get_logger
from app.models.derived import Alert, ClientDNA, EnrichedHolding
from app.models.enums import AlertStatus
from app.models.source import Client, Position

router = APIRouter(prefix="/orchestrate", tags=["orchestrate"])
log = get_logger(__name__)

# Widgets the orchestrator may summon. Everything except BookList is client-scoped
# and receives the resolved client_id injected server-side.
_CLIENT_SCOPED: set[str] = {
    "Client360",
    "PortfolioView",
    "BeforeAfter",
    "MeetingPrep",
    "EmailDraft",
    "DnaCard",
    "AllocationDonut",
    "DriftBars",
    "FitHeatmap",
    "ConflictsList",
    "SectorTreemap",
}
_ALLOWED: set[str] = _CLIENT_SCOPED | {"ClientBook"}
_MAX_WIDGETS = 4

_BOOK_MANDATES = {"defensive": "Defensive", "balanced": "Balanced", "growth": "Growth"}
_BOOK_SORTS = {"fit_desc", "fit_asc", "conflicts_desc", "name"}


def _sanitize_clientbook_props(props: Any) -> dict:
    """Whitelist the ClientBook filter props — the model sets them, we validate.

    Anything outside the known keys / value ranges is dropped, so a malformed or
    adversarial widget spec can never inject arbitrary props into the client.
    """
    if not isinstance(props, dict):
        return {}
    out: dict[str, Any] = {}

    mandate = props.get("mandate")
    if isinstance(mandate, str) and mandate.lower() in _BOOK_MANDATES:
        out["mandate"] = _BOOK_MANDATES[mandate.lower()]

    if props.get("hasConflicts") is True:
        out["hasConflicts"] = True

    for key in ("minFit", "maxFit"):
        val = props.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and 0 <= val <= 100:
            out[key] = float(val)

    sort_by = props.get("sortBy")
    if isinstance(sort_by, str) and sort_by in _BOOK_SORTS:
        out["sortBy"] = sort_by

    title = props.get("title")
    if isinstance(title, str) and title.strip():
        out["title"] = title.strip()[:60]

    return out

_CATALOG = """\
- Client360 — RICH client snapshot: profile + full DNA (values, red-lines, context, life
  events) + a portfolio-health strip. PREFER THIS for "show/open <client>" or any profile
  request — it is the primary client view.
- PortfolioView — RICH portfolio analysis: holdings table (weight, CIO view, values-fit,
  risk flags) + an AI swap proposal (before/after, human-approval). PREFER THIS for
  portfolio / holdings / allocation / drift / swap requests.
- BeforeAfter — the pitch screen: a before/after portfolio proving values are honoured while
  staying 100% within CIO (mandate-neutral weights, fit lift, per-swap deltas, human-approval).
  USE for "before/after", "what changed", "show the personalisation for <client>", "values vs CIO".
- MeetingPrep — a meeting-prep brief: a suggested agenda built from the client's DNA
  (life events, open promises, values) plus key facts. USE for "prep for my meeting with
  <client>", "what should I cover with <client>".
- EmailDraft — the grounded client message draft: editable text, a tone toggle (re-writes
  via the LLM), the locked compliance facts, and approve/send-test. USE for "draft an
  email/message to <client>", "write to <client>", "reach out to <client>".
- DnaCard — compact DNA-only card (use only if the user explicitly wants just the DNA).
- AllocationDonut — sub-asset-class allocation vs target, as a donut.
- DriftBars — drift per sub-asset-class, flagging ±2pp breaches.
- FitHeatmap — per-holding values-fit heatmap.
- ConflictsList — holdings that violate the client's stated exclusions.
- SectorTreemap — sector exposure of the portfolio.
- ClientBook — the RM's client book as a FILTERABLE table. USE THIS for "show me the
  clients", "my book", and any book-level filter/sort ("which clients have conflicts", "my
  Growth clients", "lowest-fit clients", "clients below 60 fit"). It takes optional props
  (set the ones the request implies, leave the rest out):
    • mandate: "Defensive" | "Balanced" | "Growth"
    • hasConflicts: true  (only clients with values conflicts)
    • minFit / maxFit: number 0–100  (values-fit range; "below 60" → maxFit 60)
    • sortBy: "fit_desc" | "fit_asc" | "conflicts_desc" | "name"  (e.g. "worst fit" → fit_asc)
    • title: a short label describing the filter, e.g. "Growth clients with conflicts"
  Example: "which growth clients have conflicts?" →
    {"component":"ClientBook","props":{"mandate":"Growth","hasConflicts":true,"sortBy":"conflicts_desc","title":"Growth clients with conflicts"}}"""


# --------------------------------------------------------------------------- #
# Wire models
# --------------------------------------------------------------------------- #
class ChatTurn(BaseModel):
    role: str
    content: str


class OrchestrateRequest(BaseModel):
    query: str
    scope: str = "all"
    client_id: str | None = None
    history: list[ChatTurn] = Field(default_factory=list)


class WidgetSpec(BaseModel):
    component: str
    props: dict[str, Any] = Field(default_factory=dict)


class OrchestrateResponse(BaseModel):
    reply: str
    specs: list[WidgetSpec] = Field(default_factory=list)
    client_id: str | None = None
    client_name: str | None = None


# LLM output contract
class _LLMWidget(BaseModel):
    component: str
    props: dict[str, Any] = Field(default_factory=dict)

    @field_validator("props", mode="before")
    @classmethod
    def _coerce_props(cls, v: Any) -> dict:
        return v if isinstance(v, dict) else {}


class _LLMOutput(BaseModel):
    reply: str
    # The client this turn is about, by full name. Lets the server resolve focus
    # even when the user's spelling was off and the model normalised it.
    client: str | None = None
    widgets: list[_LLMWidget] = Field(default_factory=list)

    @field_validator("widgets", mode="before")
    @classmethod
    def _coerce_widgets(cls, v: Any) -> list:
        return v if isinstance(v, list) else []


# --------------------------------------------------------------------------- #
# Focus-client resolution
# --------------------------------------------------------------------------- #
async def _load_clients(session: AsyncSession) -> list[Client]:
    return list((await session.execute(select(Client))).scalars().all())


_FUZZY_THRESHOLD = 0.8


def _match_client(query: str, clients: list[Client]) -> Client | None:
    """Resolve a client from free text.

    Two passes so typos still land: (1) exact name-token substring (longest wins),
    then (2) fuzzy — the closest client name-token to any query word, e.g.
    "Julina" -> "Julian". Fuzzy only fires when no exact token matched.
    """
    lower = query.lower()

    # 1) exact token substring
    best: Client | None = None
    best_len = 0
    for c in clients:
        name = (c.name or "").lower()
        for tok in [name, *name.split()]:
            if len(tok) >= 3 and tok in lower and len(tok) > best_len:
                best, best_len = c, len(tok)
    if best is not None:
        return best

    # 2) fuzzy per-word (handles misspellings)
    qwords = [w for w in re.findall(r"[a-zà-ÿ]+", lower) if len(w) >= 4]
    best_ratio = 0.0
    for c in clients:
        for tok in (c.name or "").lower().split():
            if len(tok) < 4:
                continue
            for qw in qwords:
                ratio = SequenceMatcher(None, qw, tok).ratio()
                if ratio > best_ratio:
                    best, best_ratio = c, ratio
    return best if best_ratio >= _FUZZY_THRESHOLD else None


async def _resolve_focus(
    session: AsyncSession,
    req: OrchestrateRequest,
    clients: list[Client],
) -> Client | None:
    if req.client_id:
        try:
            cid = uuid.UUID(req.client_id)
        except ValueError:
            cid = None
        if cid is not None:
            for c in clients:
                if c.id == cid:
                    return c
    named = _match_client(req.query, clients)
    if named is not None:
        return named
    # Fall back to a client named earlier in the conversation
    for turn in reversed(req.history):
        named = _match_client(turn.content, clients)
        if named is not None:
            return named
    return None


# --------------------------------------------------------------------------- #
# Grounded context
# --------------------------------------------------------------------------- #
def _dna_terms(items: list | None, key_order=("value", "text", "tag")) -> list[str]:
    out: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            for k in key_order:
                if item.get(k):
                    out.append(str(item[k]))
                    break
        elif item:
            out.append(str(item))
    return out[:8]


async def _build_context(session: AsyncSession, client: Client) -> str:
    """Compact, grounded brief on the focus client for the LLM to reason over."""
    lines: list[str] = [
        f"Focus client: {client.name} (mandate: {client.mandate.value if client.mandate else 'n/a'})."
    ]

    dna = await session.scalar(select(ClientDNA).where(ClientDNA.client_id == client.id))
    if dna is not None:
        values = _dna_terms(dna.values)
        exclusions = _dna_terms(dna.exclusions)
        tilts = _dna_terms(dna.tilts)
        promises = _dna_terms(dna.promises)
        life = _dna_terms(dna.life_events)
        if values:
            lines.append(f"Values: {', '.join(values)}.")
        if exclusions:
            lines.append(f"Exclusions (red lines): {', '.join(exclusions)}.")
        if tilts:
            lines.append(f"Tilts: {', '.join(tilts)}.")
        if promises:
            lines.append(f"Open promises: {', '.join(promises)}.")
        if life:
            lines.append(f"Life events: {', '.join(life)}.")
        if dna.temperament:
            lines.append(f"Temperament: {dna.temperament}.")
        if dna.business_context:
            lines.append(f"Business context: {dna.business_context}.")
    else:
        lines.append("No DNA profile extracted yet.")

    # Value-weighted portfolio fit + conflict count (same formula as /book)
    num = func.sum(
        case(
            (EnrichedHolding.fit_score.isnot(None), Position.current_chf * EnrichedHolding.fit_score),
            else_=0.0,
        )
    )
    den = func.nullif(
        func.sum(case((EnrichedHolding.fit_score.isnot(None), Position.current_chf), else_=0.0)),
        0.0,
    )
    row = (
        await session.execute(
            select(
                (num / den).label("fit"),
                func.count(Position.id).label("total"),
                func.sum(case((EnrichedHolding.fit_score == 0.0, 1), else_=0)).label("conflicts"),
            )
            .select_from(Position)
            .outerjoin(EnrichedHolding, EnrichedHolding.position_id == Position.id)
            .where(Position.client_id == client.id)
        )
    ).one()
    if row.total:
        fit_txt = f"{float(row.fit):.2f}" if row.fit is not None else "n/a"
        lines.append(
            f"Portfolio: {int(row.total)} holdings, value-weighted values-fit {fit_txt}, "
            f"{int(row.conflicts or 0)} holding(s) conflicting with stated exclusions."
        )

    # Open alerts summary
    alert_rows = (
        await session.execute(
            select(Alert.severity, func.count(Alert.id))
            .where(Alert.client_id == client.id, Alert.status == AlertStatus.OPEN)
            .group_by(Alert.severity)
        )
    ).all()
    if alert_rows:
        parts = [
            f"{int(cnt)} {sev.value if hasattr(sev, 'value') else sev}" for sev, cnt in alert_rows
        ]
        lines.append(f"Open alerts: {', '.join(parts)}.")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #
def _system_prompt(focus_name: str | None, client_names: list[str]) -> str:
    focus_line = (
        f"The client currently in focus is {focus_name}."
        if focus_name
        else "No single client is in focus yet."
    )
    roster = ", ".join(client_names[:40]) if client_names else "none loaded"
    return f"""You are the AI copilot inside a Swiss private-bank Wealth Advisor Workbench. \
You talk to a relationship manager (RM) — a human professional. Be warm, concise and \
specific. Have a real conversation: answer the question that was asked, reference the \
client's actual DNA and portfolio from the CONTEXT, and suggest the next sensible step.

{focus_line}
Clients in this book: {roster}.

You can render generative-UI widgets to show data. Available widgets:
{_CATALOG}

HARD RULES:
1. If the RM asks to SEE, SHOW, PULL UP, OPEN or DISPLAY something (a client, their \
profile/DNA, holdings, portfolio, allocation, drift, conflicts) — or your reply says \
"here is/here's …" — you MUST render the matching widget(s). Never promise a view in prose \
without rendering it. "Show <client> profile" → render Client360. "Portfolio / holdings / \
swap" → render PortfolioView.
2. You NEVER write specific portfolio figures (CHF amounts, percentages, fit scores) in \
your reply prose — if the RM needs numbers, render the widget that carries them. You MAY \
speak qualitatively about the client's values, exclusions, promises and life events.
3. A purely conversational turn (a greeting or a clarifying question) may have 0 widgets. \
Never render more than {_MAX_WIDGETS}.
4. Do NOT put a client id in props — the server injects it for client-scoped widgets, so \
use empty props {{}} for those. The ONE exception is ClientBook: set its documented filter \
props (mandate / hasConflicts / minFit / maxFit / sortBy / title) to match the request.
5. Set "client" to the FULL name of the client this turn is about (correcting any \
misspelling against the roster), or null if the turn is book-level / general. Always set \
it when you render a client-scoped widget.
6. If the request needs a specific client and you cannot tell which, ask the RM \
(you may render BookList).

Respond with STRICT JSON only, no markdown fences:
{{"reply": "<message>", "client": "<full name or null>", "widgets": [{{"component": "<Name>", "props": {{}}}}]}}"""


# --------------------------------------------------------------------------- #
# Fallback (LLM unreachable)
# --------------------------------------------------------------------------- #
def _fallback(query: str, focus: Client | None) -> OrchestrateResponse:
    lower = query.lower()
    specs: list[WidgetSpec] = []
    if focus is not None:
        cid = str(focus.id)
        if any(w in lower for w in ("portfolio", "allocation", "drift", "holding", "swap", "rebalanc")):
            specs = [WidgetSpec(component="PortfolioView", props={"clientId": cid})]
        else:
            specs = [WidgetSpec(component="Client360", props={"clientId": cid})]
        reply = (
            f"I couldn't reach the analysis model just now, so here's {focus.name}'s "
            "data directly. Try again in a moment for a written read-out."
        )
    elif "book" in lower or "client" in lower:
        specs = [WidgetSpec(component="ClientBook", props={})]
        reply = "The model is unreachable right now — here's your book in the meantime."
    else:
        reply = (
            "I couldn't reach the analysis model just now. Name a client (e.g. \"analyse "
            "Schneider's portfolio\") and I'll pull their data while it recovers."
        )
    return OrchestrateResponse(
        reply=reply,
        specs=specs,
        client_id=str(focus.id) if focus else None,
        client_name=focus.name if focus else None,
    )


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
@router.post("", response_model=OrchestrateResponse)
async def orchestrate(
    req: OrchestrateRequest,
    session: AsyncSession = Depends(get_session),
) -> OrchestrateResponse:
    clients = await _load_clients(session)
    focus = await _resolve_focus(session, req, clients)
    client_names = [c.name for c in clients if c.name]

    context = await _build_context(session, focus) if focus is not None else (
        "No client in focus. The RM may be asking a general or book-level question."
    )

    messages = [
        {"role": "system", "content": _system_prompt(focus.name if focus else None, client_names)},
        {"role": "system", "content": f"CONTEXT:\n{context}"},
    ]
    for turn in req.history[-6:]:
        role = "assistant" if turn.role == "assistant" else "user"
        messages.append({"role": role, "content": turn.content})
    messages.append({"role": "user", "content": req.query})

    try:
        out = await json_chat(messages, _LLMOutput, max_tokens=900, temperature=0.4)
    except Exception as exc:  # noqa: BLE001 — any LLM/parse failure degrades gracefully
        log.warning("orchestrate.llm_failed", error=str(exc), focus=focus.name if focus else None)
        return _fallback(req.query, focus)

    # Safety net: the model may have understood a misspelled client name that our
    # pre-pass matcher missed (e.g. "Julina" -> "Julian"). If so, adopt the client
    # it named so its client-scoped widgets still resolve instead of being dropped.
    if focus is None and out.client:
        named = _match_client(out.client, clients)
        if named is not None:
            focus = named
            log.info("orchestrate.focus_from_model", client=named.name, model_named=out.client)

    # Validate + ground the widgets the model asked for.
    specs: list[WidgetSpec] = []
    focus_id = str(focus.id) if focus else None
    for w in out.widgets[:_MAX_WIDGETS]:
        if w.component not in _ALLOWED:
            log.info("orchestrate.widget_rejected", component=w.component)
            continue
        if w.component in _CLIENT_SCOPED:
            if focus_id is None:
                continue  # client-scoped widget with no client in focus — drop
            props = {"clientId": focus_id}  # server owns the id; never trust the model's
        elif w.component == "ClientBook":
            props = _sanitize_clientbook_props(w.props)  # filter props are whitelisted
        else:
            props = {}
        specs.append(WidgetSpec(component=w.component, props=props))

    log.info(
        "orchestrate.ok",
        focus=focus.name if focus else None,
        widgets=[s.component for s in specs],
        scope=req.scope,
    )
    return OrchestrateResponse(
        reply=out.reply.strip() or "Done.",
        specs=specs,
        client_id=focus_id,
        client_name=focus.name if focus else None,
    )
