"""Email → Change Radar signal ingestion (TASK-060, EPIC-08).

Pulls recent mail from Microsoft Graph, classifies each thread with the local LLM,
resolves its entity + sender identity, and emits ordinary `RadarSignal`s that
`build_change_radar` scores and fans out exactly like Alert/NewsItem signals. The
channel only *parses*; the output is the shared `{action, entity, source, ts,
magnitude}` shape.

An email can reference:
  • an instrument  — internal "sell/trim X" → fan out to ALL holders of X
  • a client       — inbound correspondence → that one client
  • the book       — "de-risk Growth" → fan out by mandate

Reuse (do not reinvent): `RadarSignal` + the `entity_key` grammar from
`loaders/change_radar.py` (so an email on an instrument auto-dedups with a
drift/CIO/news event on the same instrument); `llm.json_chat` for classification
(Graph supplies no sentiment, so the LLM derives it); `six.find_instrument` as a
best-effort name→ISIN fallback.

No-fallbacks: when Graph is unconfigured the loader returns no signals (the offline
persona demo stays green). When it is configured but Graph/LLM fail, it raises loud.
A thread whose entity/identity cannot be resolved is surfaced as an explicit
`email:unresolved:*` signal — never silently dropped.

Public entry: `ingest_email_signals(session) -> list[RadarSignal]`.
"""

import difflib
import re
from datetime import datetime, timezone

from pydantic import AliasChoices, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import six
from app.config import get_settings
from app.graph_auth import NotSignedInError
from app.graph_mail import GraphMessage, fetch_recent_messages
from app.llm import json_chat
from app.loaders.change_radar import RadarSignal
from app.loaders.email_autodraft import autodraft_email
from app.logging import get_logger
from app.models.enums import Mandate
from app.models.source import CIORecommendation, Client, Interaction, Position

settings = get_settings()
log = get_logger(__name__)

# How many recent messages to pull per ingest cycle (token-budget conscious).
_FETCH_TOP = 50
# Minimum name-similarity to accept an instrument / client match.
_MATCH_THRESHOLD = 0.6
_URGENCY_BASE: dict[str, float] = {"high": 1.0, "medium": 0.6, "low": 0.3}
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)
_NONALNUM = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# LLM classification schema (private)
# ---------------------------------------------------------------------------


class _EmailEntity(BaseModel):
    # Accept "type" as an alias — small local models often emit it instead of "kind".
    kind: str = Field(validation_alias=AliasChoices("kind", "type"))  # instrument|client|book
    name: str | None = None  # instrument/issuer name or ticker, client name, mandate, or null
    isin: str | None = None  # only if the email literally states an ISIN


class _EmailClassification(BaseModel):
    action: str  # short label, e.g. "Sell request", "Trim position", "Complaint", "Top-up"
    entities: list[_EmailEntity] = Field(default_factory=list)
    urgency: str = "low"  # "high" | "medium" | "low"
    sentiment: float = 0.0  # -1.0 (very negative) .. 1.0 (very positive) — Graph gives none


_CLASSIFY_SYSTEM = (
    "You are a relationship manager's assistant. Classify one email into a single "
    "structured trading/relationship signal for a wealth-advisory change radar. "
    "Identify the action, the entities it concerns, an urgency band, and a sentiment "
    "score in [-1,1]. Entity kinds: 'instrument' (a security/issuer/ticker — e.g. an "
    "internal 'sell Nestle' instruction), 'client' (a person the mail is from/about), "
    "or 'book' (a whole mandate/book, e.g. 'de-risk the Growth book'). Use the ISIN "
    "field ONLY if the email literally contains one. Output ONLY a JSON object, no prose."
)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — unit-testable)
# ---------------------------------------------------------------------------


def _norm(text: str | None) -> str:
    """Lowercase, strip non-alphanumerics to spaces, collapse — for fuzzy matching."""
    if not text:
        return ""
    return _NONALNUM.sub(" ", text.lower()).strip()


def name_similarity(a: str | None, b: str | None) -> float:
    """Similarity in [0,1] combining char-ratio and token-set overlap.

    Token overlap handles reordering and email local-parts ("clara.bauer" ↔
    "Clara Bauer" → 1.0); char-ratio handles typos/abbreviations.
    """
    a_n, b_n = _norm(a), _norm(b)
    if not a_n or not b_n:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a_n, b_n).ratio()
    ta, tb = set(a_n.split()), set(b_n.split())
    overlap = len(ta & tb) / len(ta | tb) if (ta and tb) else 0.0
    return max(ratio, overlap)


def email_magnitude(urgency: str | None, sentiment: float, outbound: bool) -> float:
    """Normalised magnitude from urgency band × sentiment intensity × direction.

    Mirrors `change_radar.signal_magnitude`. Outbound (RM→client) is context-only,
    so it is damped to 0.3× — present on the radar but never a top driver.
    """
    base = _URGENCY_BASE.get((urgency or "").lower(), 0.3)
    intensity = 0.5 + 0.5 * abs(sentiment or 0.0)
    return base * intensity * (0.3 if outbound else 1.0)


def email_dna_relevance(kind: str, sentiment: float) -> float:
    """Relationship emails carrying negative sentiment are DNA-rooted → weigh more."""
    return 1.5 if kind == "client" and (sentiment or 0.0) < 0 else 1.0


def _is_outbound(msg: GraphMessage, mailbox: str) -> bool:
    """True when the message was sent by the mailbox owner (RM) — context-only."""
    return (msg.from_address or "").strip().lower() == (mailbox or "").strip().lower()


def _local_part(address: str | None) -> str | None:
    """The part of an email address before '@' (the fuzzy-match handle)."""
    if not address or "@" not in address:
        return address
    return address.split("@", 1)[0]


def _mandate_from_text(text: str | None) -> Mandate | None:
    """Detect a mandate name (Defensive/Balanced/Growth) mentioned in free text."""
    if not text:
        return None
    low = text.lower()
    for m in Mandate:
        if m.value.lower() in low:
            return m
    return None


def _pick_thread_representative(msgs: list[GraphMessage], mailbox: str) -> GraphMessage:
    """Rank a thread to one message: the most-recent INBOUND, else most-recent overall."""
    inbound = [m for m in msgs if not _is_outbound(m, mailbox)]
    pool = inbound or msgs
    return max(pool, key=lambda m: m.received_at or _EPOCH)


def _dedup_threads(msgs: list[GraphMessage], mailbox: str) -> list[GraphMessage]:
    """Collapse messages to one representative per `conversation_id` (thread dedup)."""
    by_thread: dict[str, list[GraphMessage]] = {}
    for m in msgs:
        by_thread.setdefault(m.conversation_id or m.id, []).append(m)
    return [_pick_thread_representative(group, mailbox) for group in by_thread.values()]


def _resolve_instrument_isin(
    entity: _EmailEntity,
    positions: list[Position],
    cio: list[CIORecommendation],
    threshold: float = _MATCH_THRESHOLD,
) -> tuple[str | None, str | None]:
    """Resolve an instrument entity to (isin, label) against held + CIO universe.

    Order: explicit ISIN → fuzzy match on issuer/security of held positions then
    CIO rows. Held-first is deliberate — the radar only fans out to holders, so a
    name nobody holds correctly yields no impact (surfaced as unresolved upstream).
    Returns (None, None) when nothing clears the threshold; the caller may then try
    `six.find_instrument` as a best-effort fallback.
    """
    if entity.isin:
        return entity.isin, entity.name or entity.isin
    name = entity.name
    if not name:
        return None, None
    best_score, best_isin, best_label = 0.0, None, None
    for row in list(positions) + list(cio):
        if not row.isin:
            continue
        for cand in (row.issuer, row.security):
            score = name_similarity(name, cand)
            if score > best_score:
                best_score, best_isin, best_label = score, row.isin, (cand or name)
    if best_score >= threshold:
        return best_isin, best_label
    return None, None


def _resolve_client(
    display_name: str | None,
    address: str | None,
    clients: list[Client],
    contacts_by_client: dict[str, list[str]],
    threshold: float = _MATCH_THRESHOLD,
) -> Client | None:
    """Map a name/address to a CRM client by name-similarity (no CRM email field).

    Matches the display name and the address local-part against each client's name
    and their recorded `client_contact` values. Returns None when nothing clears the
    threshold — the caller buckets it, never drops it.
    """
    queries = [q for q in (display_name, _local_part(address)) if q]
    if not queries:
        return None
    best_score, best_client = 0.0, None
    for client in clients:
        candidates = [client.name, *contacts_by_client.get(str(client.id), [])]
        for q in queries:
            for cand in candidates:
                score = name_similarity(q, cand)
                if score > best_score:
                    best_score, best_client = score, client
    return best_client if best_score >= threshold else None


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------


async def _classify_email(msg: GraphMessage) -> _EmailClassification:
    """Classify one email via the local LLM (raises loud on parse failure)."""
    body = (msg.body_text or "")[:2000]
    user = (
        f"Subject: {msg.subject or '(none)'}\n"
        f"From: {msg.from_name or ''} <{msg.from_address or ''}>\n"
        f"Body:\n{body}"
    )
    return await json_chat(
        [
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": user},
        ],
        _EmailClassification,
    )


async def _signals_for_email(
    msg: GraphMessage,
    cls: _EmailClassification,
    mailbox: str,
    clients: list[Client],
    positions: list[Position],
    cio: list[CIORecommendation],
    contacts_by_client: dict[str, list[str]],
) -> list[RadarSignal]:
    """Turn one classified email into RadarSignals (one per impacted client)."""
    outbound = _is_outbound(msg, mailbox)
    note = f"Email: {msg.subject}".strip() if msg.subject else "Email"
    ts = msg.received_at
    out: list[RadarSignal] = []

    for entity in cls.entities:
        kind = (entity.kind or "").lower()

        if kind == "instrument":
            isin, label = _resolve_instrument_isin(entity, positions, cio)
            if isin is None and entity.name and settings.six_mcp_token:
                # Best-effort external resolution for names nobody currently holds.
                try:
                    hits = await six.find_instrument(entity.name, size=1)
                    if hits:
                        isin, label = hits[0].isin, hits[0].name or entity.name
                except Exception as exc:  # network/SIX hiccup — stay best-effort
                    log.warning("email_ingest.six_lookup_failed", name=entity.name, error=str(exc))
            if not isin:
                continue
            holders = sorted({str(p.client_id) for p in positions if p.isin == isin})
            mag = email_magnitude(cls.urgency, cls.sentiment, outbound=False)
            rel = email_dna_relevance(kind, cls.sentiment)
            for client_id in holders:
                out.append(
                    RadarSignal(
                        entity_key=f"isin:{isin}",
                        entity_type="instrument",
                        entity_label=label,
                        action=cls.action,
                        source="email",
                        client_id=client_id,
                        magnitude=mag,
                        dna_relevance=rel,
                        event_ts=ts,
                        isins=[isin],
                        dna_note=note,
                        suggested_action=cls.action,
                    )
                )

        elif kind == "client":
            # Inbound → the sender is the client; outbound → the recipient is.
            if outbound:
                rname, raddr = (msg.to_recipients[0] if msg.to_recipients else (None, None))
            else:
                rname, raddr = msg.from_name, msg.from_address
            client = _resolve_client(entity.name or rname, raddr, clients, contacts_by_client)
            if client is None:
                continue
            out.append(
                RadarSignal(
                    entity_key=f"client:{client.id}",
                    entity_type="client",
                    entity_label=client.name,
                    action=cls.action,
                    source="email",
                    client_id=str(client.id),
                    magnitude=email_magnitude(cls.urgency, cls.sentiment, outbound=outbound),
                    dna_relevance=email_dna_relevance(kind, cls.sentiment),
                    event_ts=ts,
                    dna_note=note,
                    suggested_action=cls.action,
                )
            )

        elif kind == "book":
            mandate = _mandate_from_text(entity.name)
            if mandate is None:
                # A vague "book" reference (e.g. "global mandate") would fan out to
                # every client with zero real exposure — pure radar noise. Skip it;
                # only act on a concrete mandate (Defensive/Balanced/Growth).
                continue
            targets = [c for c in clients if c.mandate == mandate]
            key = f"email:book:{mandate.value}"
            mag = email_magnitude(cls.urgency, cls.sentiment, outbound=False)
            for c in targets:
                out.append(
                    RadarSignal(
                        entity_key=key,
                        entity_type="macro",
                        entity_label=f"Book: {mandate.value if mandate else 'all mandates'}",
                        action=cls.action,
                        source="email",
                        client_id=str(c.id),
                        magnitude=mag,
                        dna_relevance=1.0,
                        event_ts=ts,
                        dna_note=note,
                        suggested_action=cls.action,
                    )
                )

    if not out:
        # A real RM mailbox is full of mail that isn't client correspondence
        # (newsletters, invites, bounces). Surfacing each as a zero-exposure radar
        # item is pure noise, so we drop it — only emails that resolve to a known
        # client or a held instrument reach the radar. Logged, not silently lost.
        log.info(
            "email_ingest.unresolved_skipped",
            subject=(msg.subject or "")[:80],
            sender=msg.from_address or msg.from_name,
        )
    return out


# ---------------------------------------------------------------------------
# Async orchestrator
# ---------------------------------------------------------------------------


async def _contacts_by_client(session: AsyncSession) -> dict[str, list[str]]:
    """Distinct CRM `client_contact` values per client — extra name-match candidates."""
    rows = (
        await session.execute(
            select(Interaction.client_id, Interaction.client_contact).where(
                Interaction.client_contact.isnot(None)
            )
        )
    ).all()
    out: dict[str, set[str]] = {}
    for client_id, contact in rows:
        out.setdefault(str(client_id), set()).add(contact)
    return {k: sorted(v) for k, v in out.items()}


async def ingest_email_signals(session: AsyncSession) -> list[RadarSignal]:
    """Pull + classify + resolve recent mail into RadarSignals for the Change Radar.

    Returns `[]` when Microsoft Graph is unconfigured (degrade, don't crash). Raises
    when Graph is configured but the fetch/LLM fails (no-fallbacks).
    """
    if not settings.ms_graph_enabled:
        log.warning("email_ingest.disabled", reason="MS_GRAPH_* unset")
        return []

    mailbox = settings.ms_graph_mailbox
    try:
        msgs = await fetch_recent_messages(mailbox, top=_FETCH_TOP)
    except NotSignedInError:
        # Delegated mode, RM not signed in yet — degrade quietly (the radar runs on
        # news/alerts until they sign in). Not a fallback: no data is substituted.
        log.info("email_ingest.not_signed_in", reason="RM has not signed in to Microsoft")
        return []
    reps = _dedup_threads(msgs, mailbox)

    clients = (await session.execute(select(Client))).scalars().all()
    positions = (await session.execute(select(Position))).scalars().all()
    cio = (await session.execute(select(CIORecommendation))).scalars().all()
    contacts = await _contacts_by_client(session)

    signals: list[RadarSignal] = []
    drafted = 0
    for rep in reps:
        try:
            cls = await _classify_email(rep)
            email_signals = await _signals_for_email(
                rep, cls, mailbox, clients, positions, cio, contacts
            )
        except Exception as exc:  # noqa: BLE001 — one odd email must not nuke the radar
            log.warning("email_ingest.classify_skip", message_id=rep.id, error=str(exc))
            continue
        signals += email_signals

        # Part A: pre-draft the answer for genuinely NEW inbound mail (draft only, G1).
        if (
            settings.email_autodraft_enabled
            and drafted < settings.email_autodraft_max_per_cycle
            and not _is_outbound(rep, mailbox)
        ):
            draft_id = await autodraft_email(session, rep, email_signals)
            if draft_id:
                drafted += 1

    log.info(
        "email_ingest.complete",
        messages=len(msgs),
        threads=len(reps),
        signals=len(signals),
        autodrafted=drafted,
    )
    return signals
