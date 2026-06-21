"""Microsoft Graph mail client (TASK-060/061, EPIC-08).

Email transport for the Change Radar (inbound) and the RM message handoff (outbound).
SCOPED EXCEPTION to the "no Azure" rule (Requirements §20): Azure is used here ONLY
as an email transport, never as infrastructure.

Two auth modes (settings.ms_graph_auth_mode):
  app       → client-credentials, app-only (read-only inbound, original TASK-060).
  delegated → the RM signs in (graph_auth, TASK-061); reads/sends THROUGH the shared
              mailbox on the RM's behalf (Mail.Read.Shared / Mail.Send.Shared).

Outbound (`send_via_graph`) is RM-only by construction and EXPLICIT-action only —
it is never called from an autonomous loop without a human in the path (autonomy
boundary G1). The proactive dispatch reaches the RM, never the client.

Mirrors the structure of `app/six.py` (module-level singleton `httpx.AsyncClient`,
`get_settings`, `ping_*`/`close_*` lifespan hooks). The app-only token is short-lived
and cached here; the delegated token is owned by `graph_auth` (cached in Redis).

No-fallbacks: a *configured* mailbox that fails to authenticate, fetch, or send
raises loudly. Graph returning zero messages is a legitimate empty result.

Public API:
  fetch_recent_messages(mailbox, since, top) → list[GraphMessage]
  send_via_graph(mailbox, to, subject, body, ...) → None  (explicit RM action)
  ping_graph()  → bool   (lifespan health check)
  close_graph() → None   (lifespan shutdown)
"""

import re
import time
from datetime import datetime

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

_client: httpx.AsyncClient | None = None
# Cached app-only token: (access_token, unix_expiry). Re-acquired past expiry.
_token_cache: tuple[str, float] | None = None
# Refresh a little before the real expiry to avoid using a token mid-flight.
_TOKEN_SKEW_SECONDS = 60
# Page cap when following @odata.nextLink (token-budget conscious, like news polling).
_MAX_PAGES = 5
# Strip HTML tags / collapse whitespace without pulling in a parser dependency.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


class GraphMessage(BaseModel):
    """One Graph message, flattened to the fields the ingest pipeline needs."""

    id: str
    conversation_id: str | None = None
    subject: str | None = None
    body_text: str | None = None
    from_name: str | None = None
    from_address: str | None = None
    to_recipients: list[tuple[str | None, str | None]] = []  # (name, address)
    received_at: datetime | None = None


# ---------------------------------------------------------------------------
# Singleton client + token
# ---------------------------------------------------------------------------


def _get_client() -> httpx.AsyncClient:
    """Lazy singleton — built once, reused process-wide."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
        log.info("graph.init", base_url=settings.ms_graph_base_url)
    return _client


async def _token() -> str:
    """Return a Graph access token for the configured auth mode.

    delegated → the RM's signed-in token (graph_auth, refreshed silently); raises
                NotSignedInError when the RM is not signed in.
    app       → an app-only client-credentials token, cached here until expiry;
                raises httpx.HTTPStatusError on auth failure.
    Either way the caller fails loud (no-fallbacks).
    """
    if settings.ms_graph_auth_mode.strip().lower() == "delegated":
        # Imported lazily to avoid a hard MSAL dependency in the app-only path.
        from app import graph_auth

        return await graph_auth.get_access_token()

    global _token_cache
    now = time.time()
    if _token_cache is not None and _token_cache[1] - _TOKEN_SKEW_SECONDS > now:
        return _token_cache[0]

    url = f"{settings.ms_graph_authority}/{settings.ms_graph_tenant_id}/oauth2/v2.0/token"
    resp = await _get_client().post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": settings.ms_graph_client_id,
            "client_secret": settings.ms_graph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload["access_token"]
    expires_in = float(payload.get("expires_in", 3600))
    _token_cache = (token, now + expires_in)
    log.info("graph.token_acquired", expires_in=expires_in)
    return token


# ---------------------------------------------------------------------------
# Parsing helpers (pure — unit-testable)
# ---------------------------------------------------------------------------


def _html_to_text(content: str | None) -> str | None:
    """Strip HTML tags and collapse whitespace (no parser dependency)."""
    if not content:
        return None
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", content)).strip() or None


def _parse_message(raw: dict) -> GraphMessage:
    """Flatten one Graph `message` resource into a GraphMessage."""
    body = raw.get("body") or {}
    body_content = body.get("content")
    # Prefer the full body; fall back to the preview Graph always supplies.
    body_text = _html_to_text(body_content) or (raw.get("bodyPreview") or None)

    sender = ((raw.get("from") or {}).get("emailAddress")) or {}
    recipients: list[tuple[str | None, str | None]] = []
    for r in raw.get("toRecipients") or []:
        addr = (r or {}).get("emailAddress") or {}
        recipients.append((addr.get("name"), addr.get("address")))

    received = raw.get("receivedDateTime")
    received_at: datetime | None = None
    if received:
        # Graph emits RFC-3339 with a trailing Z; datetime.fromisoformat needs +00:00.
        received_at = datetime.fromisoformat(received.replace("Z", "+00:00"))

    return GraphMessage(
        id=raw.get("id", ""),
        conversation_id=raw.get("conversationId"),
        subject=raw.get("subject"),
        body_text=body_text,
        from_name=sender.get("name"),
        from_address=sender.get("address"),
        to_recipients=recipients,
        received_at=received_at,
    )


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def fetch_recent_messages(
    mailbox: str,
    since: datetime | None = None,
    top: int = 50,
) -> list[GraphMessage]:
    """Pull recent messages from a mailbox, newest first.

    `since` (UTC) adds a `receivedDateTime ge` filter; `top` bounds the first page.
    Follows `@odata.nextLink` up to `_MAX_PAGES`. Raises on any HTTP error.
    """
    token = await _token()
    params: dict[str, str | int] = {
        "$select": "id,conversationId,subject,bodyPreview,body,from,toRecipients,receivedDateTime",
        "$orderby": "receivedDateTime desc",
        "$top": top,
    }
    if since is not None:
        iso = since.isoformat().replace("+00:00", "Z")
        params["$filter"] = f"receivedDateTime ge {iso}"

    url: str | None = f"{settings.ms_graph_base_url}/users/{mailbox}/messages"
    client = _get_client()
    messages: list[GraphMessage] = []
    pages = 0
    while url and pages < _MAX_PAGES:
        # Only the first request carries query params; nextLink already encodes them.
        resp = await client.get(
            url,
            params=params if pages == 0 else None,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        payload = resp.json()
        for raw in payload.get("value", []):
            messages.append(_parse_message(raw))
        url = payload.get("@odata.nextLink")
        pages += 1

    log.info("graph.fetch_complete", mailbox=mailbox, messages=len(messages), pages=pages)
    return messages


async def send_via_graph(
    mailbox: str,
    to: str,
    subject: str,
    body: str,
    *,
    html: bool = False,
    save_to_sent: bool = True,
) -> None:
    """Send one message THROUGH `mailbox` (the shared mailbox) to `to`.

    Delegated Mail.Send.Shared: the signed-in RM sends on behalf of the shared
    mailbox. EXPLICIT RM action only — never call this from an autonomous loop
    without a human in the path (autonomy boundary G1). Raises on any HTTP error
    (a 202 Accepted is success).
    """
    token = await _token()
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML" if html else "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": save_to_sent,
    }
    resp = await _get_client().post(
        f"{settings.ms_graph_base_url}/users/{mailbox}/sendMail",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    log.info("graph.send_ok", mailbox=mailbox, subject=subject)


async def create_calendar_event(
    mailbox: str,
    subject: str,
    start_iso: str,
    end_iso: str,
    *,
    body: str | None = None,
    timezone: str = "Europe/Zurich",
    reminder_minutes: int = 15,
) -> dict:
    """Create a calendar event in `mailbox` (delegated Calendars.ReadWrite).

    `start_iso`/`end_iso` are naive ISO-8601 local datetimes (no offset) interpreted
    in `timezone`. EXPLICIT RM action only (the RM committed the note) — never an
    autonomous loop (autonomy boundary G1). Returns the created event (incl. webLink);
    raises on any HTTP error.
    """
    token = await _token()
    payload = {
        "subject": subject,
        "start": {"dateTime": start_iso, "timeZone": timezone},
        "end": {"dateTime": end_iso, "timeZone": timezone},
        "isReminderOn": True,
        "reminderMinutesBeforeStart": reminder_minutes,
    }
    if body:
        payload["body"] = {"contentType": "Text", "content": body}
    resp = await _get_client().post(
        f"{settings.ms_graph_base_url}/users/{mailbox}/events",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    event = resp.json()
    log.info("graph.event_created", mailbox=mailbox, subject=subject, event_id=event.get("id"))
    return event


async def ping_graph() -> bool:
    """Lightweight connectivity check — token + a single-message probe."""
    if not settings.ms_graph_enabled:
        return False
    try:
        await fetch_recent_messages(settings.ms_graph_mailbox, top=1)
        return True
    except Exception as exc:
        log.warning("graph.ping_failed", error=str(exc))
        return False


async def close_graph() -> None:
    """Release the HTTP connection pool on app shutdown."""
    global _client, _token_cache
    if _client is not None:
        await _client.aclose()
        _client = None
        _token_cache = None
        log.info("graph.closed")
