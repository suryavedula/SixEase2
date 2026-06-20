"""Message Agent — delegates to the Message Generator engine (TASK-054 / EPIC-13).

ST5 mapping: Message Agent → Message Generator
  MSG2: loaders/fact_sheet.py:assemble_fact_sheet  (builds locked fact sheet)
  MSG3: loaders/message_render.py:render_message_draft (renders styled prose + guardrail)

params accepted:
  draft_id  (str | UUID) — skip MSG2 and render an existing draft directly
  alert_id  (str | UUID) — anchor MSG2 to a specific alert (otherwise picks latest open)
  preset    (str)        — "data-driven" | "values-led" | "balanced" (MSG3 style toggle)

If draft_id is absent, the agent runs the full two-step MSG2 → MSG3 pipeline.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentRequest, AgentResult
from app.loaders.fact_sheet import assemble_fact_sheet
from app.loaders.message_render import render_message_draft
from app.logging import get_logger

log = get_logger(__name__)


async def invoke(request: AgentRequest, session: AsyncSession) -> AgentResult:
    """Assemble fact sheet (if needed) then render the advisory draft."""
    client_id = request.client_id
    params = request.params
    log.info("agent.invoke.start", agent="message", client_id=str(client_id))

    try:
        # Resolve draft_id — either passed in or created by assemble_fact_sheet.
        raw_draft_id = params.get("draft_id")
        if raw_draft_id is not None:
            draft_id = uuid.UUID(str(raw_draft_id)) if not isinstance(raw_draft_id, uuid.UUID) else raw_draft_id
        else:
            raw_alert_id = params.get("alert_id")
            alert_id = (
                uuid.UUID(str(raw_alert_id))
                if raw_alert_id is not None and not isinstance(raw_alert_id, uuid.UUID)
                else raw_alert_id
            )
            fs_result = await assemble_fact_sheet(session, client_id, alert_id=alert_id)
            draft_id = uuid.UUID(fs_result["draft_id"])
            log.info(
                "agent.fact_sheet_assembled",
                agent="message",
                client_id=str(client_id),
                draft_id=str(draft_id),
            )

        preset = params.get("preset") or None
        render_result = await render_message_draft(session, draft_id, preset_override=preset)

        payload = {
            "draft_id": render_result["draft_id"],
            "preset": render_result["preset"],
            "draft_text": render_result["draft_text"],
            "guardrail_passed": render_result["guardrail_passed"],
        }
        log.info(
            "agent.invoke.done",
            agent="message",
            client_id=str(client_id),
            draft_id=render_result["draft_id"],
            preset=render_result["preset"],
        )
        return AgentResult(
            agent="message",
            client_id=client_id,
            status="ok",
            payload=payload,
        )

    except Exception as exc:  # noqa: BLE001
        log.error(
            "agent.invoke.error", agent="message", client_id=str(client_id), error=str(exc)
        )
        return AgentResult(
            agent="message",
            client_id=client_id,
            status="error",
            payload={},
            error=str(exc),
        )
