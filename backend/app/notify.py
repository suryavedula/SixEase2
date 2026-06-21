"""RM-only outbound email transport (EPIC-08 — proactive dispatch).

The ONLY module in the backend that *sends* proactive mail outbound. It targets the
relationship manager (`settings.rm_email`) ONLY — never a client. This is the
human-in-the-loop boundary in code: the proactive radar reaches the RM first, and
the RM remains the sole party who ever contacts the client (autonomy boundary G1,
§3).

Two transports, selected at call time:
  Microsoft Graph (preferred) — when `ms_graph_send_enabled` and the RM is signed
                                 in; sends through the shared mailbox to the RM.
  SMTP / MailHog (default)     — otherwise; defaults suit a local MailHog container.

Both degrade to a logged no-op when unconfigured/unavailable, so dispatch never
crashes on a missing mail server.
"""

from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings
from app.logging import get_logger

settings = get_settings()
log = get_logger(__name__)


def smtp_enabled() -> bool:
    """True when an SMTP host and an RM recipient are both configured."""
    return bool(settings.smtp_host and settings.rm_email)


def graph_send_enabled() -> bool:
    """True when Graph outbound is switched on and an RM recipient is set.

    Whether the RM is actually *signed in* is decided at send time (a sign-in can
    lapse between calls) — `send_rm_email` falls through to SMTP if Graph isn't ready.
    """
    return bool(settings.ms_graph_send_enabled and settings.ms_graph_enabled and settings.rm_email)


async def _send_via_graph_rm(subject: str, html: str) -> bool:
    """Try the Graph transport (shared mailbox → RM). False if not ready/failed."""
    from app.graph_auth import NotSignedInError
    from app.graph_mail import send_via_graph

    try:
        await send_via_graph(
            settings.ms_graph_mailbox, settings.rm_email, subject, html, html=True
        )
        return True
    except NotSignedInError:
        log.info("notify.graph_not_signed_in", action="falling back to SMTP")
        return False
    except Exception as exc:  # noqa: BLE001 — dispatch must survive a Graph outage
        log.warning("notify.graph_send_failed", error=str(exc), subject=subject)
        return False


async def send_rm_email(subject: str, html: str, text: str | None = None) -> bool:
    """Send one email to the RM. Returns True on success, False on no-op/failure.

    RM-only by construction: the recipient is always `settings.rm_email`; this
    function takes no client address and must never be given one. Prefers Graph
    (shared mailbox) when enabled, otherwise SMTP/MailHog.
    """
    if graph_send_enabled() and await _send_via_graph_rm(subject, html):
        log.info("notify.email_sent", to=settings.rm_email, subject=subject, transport="graph")
        return True

    if not smtp_enabled():
        log.warning("notify.smtp_disabled", reason="SMTP_HOST/RM_EMAIL unset")
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.rm_email
    msg["To"] = settings.rm_email
    msg["Subject"] = subject
    msg.set_content(text or "This message is best viewed in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_starttls,
        )
        log.info("notify.email_sent", to=settings.rm_email, subject=subject, transport="smtp")
        return True
    except Exception as exc:  # noqa: BLE001 — dispatch must survive a mail outage
        log.warning("notify.email_failed", error=str(exc), subject=subject)
        return False
