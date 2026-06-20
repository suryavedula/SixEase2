"""LangGraph node functions for the orchestrator (TASK-053, EPIC-13).

Each node shares the same signature: async def <name>(state: AgentState) -> AgentState.
All nodes:
  - Wrap their body in try/except → set state["error"] on first failure and return cleanly
  - Append one ISO-8601-stamped entry to state["trace"] (TK5 observability)
  - Use SessionFactory for DB access — never get_session() (that is for request handlers)
  - Never import from FastAPI
"""

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select

from app.db import SessionFactory
from app.llm import json_chat
from app.loaders.fit import compute_fit
from app.loaders.swap import compute_swaps
from app.loaders.news_match import scan_news_for_client
from app.loaders.fact_sheet import assemble_fact_sheet
from app.loaders.message_render import render_message_draft
from app.loaders.task_classify import assert_auto_eligible
from app.logging import get_logger
from app.models.derived import ClientDNA
from app.models.enums import TaskKind
from app.models.source import Interaction
from app.news import search_articles
from app.agents.state import AgentState

log = get_logger(__name__)

_VALID_KINDS: dict[str, TaskKind] = {k.value: k for k in TaskKind}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# route_intent
# ---------------------------------------------------------------------------

class _KindOut(BaseModel):
    kind: str


async def route_intent(state: AgentState) -> AgentState:
    """Normalise task_kind to a known TaskKind value and enforce the autonomy boundary."""
    try:
        raw = state["task_kind"]

        if raw in _VALID_KINDS:
            kind = _VALID_KINDS[raw]
        else:
            valid_list = ", ".join(_VALID_KINDS)
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"Classify the task description into exactly one of these kinds: {valid_list}. "
                        "Respond with JSON only: {\"kind\": \"<value>\"}."
                    ),
                },
                {"role": "user", "content": state["input"]},
            ]
            out = await json_chat(messages, _KindOut, temperature=0.0, max_tokens=64)
            if out.kind not in _VALID_KINDS:
                state["error"] = f"LLM returned unknown task_kind: {out.kind!r}"
                log.warning("orchestrator.unknown_kind", task_id=state["task_id"], kind=out.kind)
                state["trace"].append(f"[{_now()}] route_intent: ERROR — {state['error']}")
                return state
            kind = _VALID_KINDS[out.kind]

        try:
            assert_auto_eligible(kind, context={"task_id": state["task_id"]})
        except ValueError as exc:
            state["error"] = str(exc)
            log.warning("orchestrator.autonomy_violation", task_id=state["task_id"], kind=kind.value)
            state["trace"].append(f"[{_now()}] route_intent: BLOCKED — {state['error']}")
            return state

        state["task_kind"] = kind.value
        state["trace"].append(f"[{_now()}] route_intent: resolved task_kind={kind.value}")
        log.info("orchestrator.routed", task_id=state["task_id"], task_kind=kind.value)

    except Exception as exc:
        state["error"] = str(exc)
        log.warning("orchestrator.route_error", task_id=state["task_id"], error=str(exc))
        state["trace"].append(f"[{_now()}] route_intent: ERROR — {exc}")

    return state


# ---------------------------------------------------------------------------
# crm_agent — RESEARCH / ANALYSIS
# ---------------------------------------------------------------------------

class _BriefOut(BaseModel):
    summary: str
    citations: list[str]


async def crm_agent(state: AgentState) -> AgentState:
    """Read existing client DNA + recent CRM notes, fetch news, synthesise a cited brief."""
    try:
        if not state["client_id"]:
            raise ValueError("crm_agent requires a client_id")

        uuid_cid = uuid.UUID(state["client_id"])

        async with SessionFactory() as session:
            dna_row: ClientDNA | None = await session.scalar(
                select(ClientDNA).where(ClientDNA.client_id == uuid_cid)
            )
            interactions = (
                await session.execute(
                    select(Interaction)
                    .where(Interaction.client_id == uuid_cid)
                    .order_by(Interaction.date.desc())
                    .limit(10)
                )
            ).scalars().all()

        # Build keyword list from DNA tags for news search
        keywords: list[str] = []
        if dna_row:
            for field in (dna_row.values, dna_row.exclusions, dna_row.tilts):
                if isinstance(field, list):
                    for item in field:
                        tag = item.get("value") or item.get("tag") if isinstance(item, dict) else None
                        if tag and isinstance(tag, str):
                            keywords.append(tag)

        # Fetch news (graceful skip on missing key or empty keywords)
        articles = []
        if keywords:
            try:
                articles = await search_articles(keywords=keywords[:5], count=20)
            except Exception as news_exc:
                log.warning("crm_agent.news_skip", error=str(news_exc), task_id=state["task_id"])

        # Build context for the brief
        notes_text = "\n".join(
            f"- [{i.date}] {i.note}" for i in interactions if i.note
        ) or "(no CRM notes)"

        dna_summary = ""
        if dna_row:
            dna_summary = (
                f"Values: {dna_row.values or []}\n"
                f"Exclusions: {dna_row.exclusions or []}\n"
                f"Tilts: {dna_row.tilts or []}\n"
                f"Business context: {dna_row.business_context or ''}\n"
                f"Family context: {dna_row.family_context or ''}\n"
                f"Temperament: {dna_row.temperament or ''}"
            )

        headlines = "\n".join(f"- {a.title}" for a in articles[:10]) or "(no articles)"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a research assistant for a relationship manager. "
                    "Synthesise a concise 2-4 sentence brief about this client "
                    "based on their DNA profile, recent CRM notes, and relevant news headlines. "
                    "Include citations as short identifiers (note date or article headline). "
                    "Respond with JSON only: {\"summary\": \"...\", \"citations\": [\"...\", ...]}."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Client DNA:\n{dna_summary}\n\n"
                    f"Recent CRM notes:\n{notes_text}\n\n"
                    f"News headlines:\n{headlines}\n\n"
                    f"Research request: {state['input']}"
                ),
            },
        ]
        brief = await json_chat(messages, _BriefOut, temperature=0.3, max_tokens=512)

        state["result"]["crm"] = {
            "summary": brief.summary,
            "citations": brief.citations,
            "notes_read": len(interactions),
            "articles_fetched": len(articles),
        }
        state["trace"].append(
            f"[{_now()}] crm_agent: notes={len(interactions)}, "
            f"articles={len(articles)}, dna_version={dna_row.version if dna_row else 'N/A'}"
        )
        log.info(
            "crm_agent.done",
            task_id=state["task_id"],
            client_id=state["client_id"],
            notes=len(interactions),
            articles=len(articles),
        )

    except Exception as exc:
        state["error"] = str(exc)
        log.warning("crm_agent.error", task_id=state["task_id"], error=str(exc))
        state["trace"].append(f"[{_now()}] crm_agent: ERROR — {exc}")

    return state


# ---------------------------------------------------------------------------
# portfolio_agent — SWAP_CANDIDATES (deterministic, no LLM)
# ---------------------------------------------------------------------------

async def portfolio_agent(state: AgentState) -> AgentState:
    """Score holdings and compute CIO-BUY swap candidates. No LLM calls."""
    try:
        if not state["client_id"]:
            raise ValueError("portfolio_agent requires a client_id")

        uuid_cid = uuid.UUID(state["client_id"])

        async with SessionFactory() as session:
            fit = await compute_fit(session, client_id=uuid_cid)
            swaps = await compute_swaps(session, client_id=uuid_cid)

        state["result"]["portfolio"] = {**fit, **swaps}
        state["trace"].append(
            f"[{_now()}] portfolio_agent: fit={fit}, swaps={swaps}"
        )
        log.info(
            "portfolio_agent.done",
            task_id=state["task_id"],
            client_id=state["client_id"],
            **fit,
            **swaps,
        )

    except Exception as exc:
        state["error"] = str(exc)
        log.warning("portfolio_agent.error", task_id=state["task_id"], error=str(exc))
        state["trace"].append(f"[{_now()}] portfolio_agent: ERROR — {exc}")

    return state


# ---------------------------------------------------------------------------
# news_agent — NEWS_GATHER
# ---------------------------------------------------------------------------

async def news_agent(state: AgentState) -> AgentState:
    """Fetch live news and match to the client's watchlist."""
    try:
        if not state["client_id"]:
            raise ValueError("news_agent requires a client_id")

        uuid_cid = uuid.UUID(state["client_id"])

        async with SessionFactory() as session:
            result = await scan_news_for_client(session, client_id=uuid_cid)

        state["result"]["news"] = result
        state["trace"].append(
            f"[{_now()}] news_agent: matched={result.get('matched', 0)}, "
            f"inserted={result.get('inserted', 0)}"
        )
        log.info(
            "news_agent.done",
            task_id=state["task_id"],
            client_id=state["client_id"],
            **result,
        )

    except Exception as exc:
        state["error"] = str(exc)
        log.warning("news_agent.error", task_id=state["task_id"], error=str(exc))
        state["trace"].append(f"[{_now()}] news_agent: ERROR — {exc}")

    return state


# ---------------------------------------------------------------------------
# message_agent — DRAFT_PREP (deterministic pipeline, one bounded LLM call)
# ---------------------------------------------------------------------------

async def message_agent(state: AgentState) -> AgentState:
    """Assemble fact sheet (no LLM) then render prose draft (one bounded LLM call)."""
    try:
        if not state["client_id"]:
            raise ValueError("message_agent requires a client_id")

        uuid_cid = uuid.UUID(state["client_id"])

        async with SessionFactory() as session:
            # MSG2: deterministic fact-sheet assembly — zero LLM calls
            fs = await assemble_fact_sheet(session, uuid_cid)
            draft_id = uuid.UUID(fs["draft_id"])
            # MSG3+MSG4: one LLM prose call + number-guardrail validation
            render = await render_message_draft(session, draft_id)

        state["result"]["message"] = {
            "draft_id": render["draft_id"],
            "preset": render["preset"],
            "draft_text": render["draft_text"],
            "guardrail_passed": render["guardrail_passed"],
        }
        state["trace"].append(
            f"[{_now()}] message_agent: draft_id={render['draft_id']}, "
            f"preset={render['preset']}, guardrail_passed={render['guardrail_passed']}"
        )
        log.info(
            "message_agent.done",
            task_id=state["task_id"],
            client_id=state["client_id"],
            draft_id=render["draft_id"],
            guardrail_passed=render["guardrail_passed"],
        )

    except Exception as exc:
        state["error"] = str(exc)
        log.warning("message_agent.error", task_id=state["task_id"], error=str(exc))
        state["trace"].append(f"[{_now()}] message_agent: ERROR — {exc}")

    return state
