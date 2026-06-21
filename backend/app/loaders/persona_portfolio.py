"""Link the four real personas to a real portfolio (TASK-056).

The portfolio workbook ships holdings only on the three "Sample" mandate
clients; the CRM personas (Räber, Schneider, Huber, Ammann) arrive with DNA but
no positions. That left the persona portfolio views empty.

Rather than serve a fallback (which would misrepresent another book's holdings
as the persona's — breaking grounding), we attach REAL positions to each
persona: the holdings of the Sample portfolio matching their mandate, copied as
owned Position rows. Downstream fit/swap/drift then compute against the persona's
OWN DNA, so personalisation is genuine.

Idempotent: a persona's existing positions are wiped before re-copying. Run the
derived pipeline (fit → swap → drift → alerts → rank) afterwards.
"""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import EnrichedHolding
from app.models.enums import Mandate
from app.models.source import Client, Position
from app.tags import instrument_tags

log = get_logger(__name__)

# Persona → mandate, matching crm.py _PERSONA_SHEETS exactly.
_PERSONA_MANDATES: dict[str, Mandate] = {
    "Eugen Räber": Mandate.DEFENSIVE,
    "Hubertus Schneider": Mandate.BALANCED,
    "Marius Huber": Mandate.BALANCED,
    "Julian Ammann": Mandate.GROWTH,
}

_SAMPLE_CLIENT_NAMES: dict[Mandate, str] = {
    Mandate.DEFENSIVE: "Sample Defensive",
    Mandate.BALANCED: "Sample Balanced",
    Mandate.GROWTH: "Sample Growth",
}


async def link_persona_portfolios(session: AsyncSession) -> dict[str, int]:
    """Copy each persona's mandate-matching Sample positions onto the persona.

    Returns {"personas_linked": N, "positions_copied": M}.
    """
    sample_positions = await _fetch_sample_positions(session)

    personas_linked = 0
    positions_copied = 0

    for name, mandate in _PERSONA_MANDATES.items():
        persona = (
            await session.execute(select(Client).where(Client.name == name))
        ).scalar_one_or_none()
        if persona is None:
            log.warning("persona_portfolio.persona_missing", name=name)
            continue

        templates = sample_positions[mandate]
        n = await _reload_positions(session, persona, templates)
        personas_linked += 1
        positions_copied += n
        log.info("persona_portfolio.linked", persona=name, mandate=mandate.value, positions=n)

    await session.commit()
    log.info(
        "persona_portfolio.complete",
        personas_linked=personas_linked,
        positions_copied=positions_copied,
    )
    return {"personas_linked": personas_linked, "positions_copied": positions_copied}


async def copy_sample_positions(
    session: AsyncSession,
    client: Client,
    mandate: Mandate,
    *,
    at_target_weight: bool = False,
) -> int:
    """Copy one mandate's Sample-portfolio holdings onto `client` as owned positions.

    Wipes the client's existing positions first (idempotent) and writes EnrichedHolding
    tags for each copied row. Returns the number of positions copied. Raises RuntimeError
    if the matching Sample portfolio has not been seeded (no-fallbacks: never substitute
    another book's holdings).

    With ``at_target_weight=True`` each holding's `current_chf` is set to its `target_chf`,
    so the book sits exactly on the CIO sub-asset-class target weights with zero drift —
    the house-model baseline the simulated-client seeder needs (TASK-064) for a pure
    instrument-only before/after. The default (False) preserves the Sample book's real
    drifted values, which is what persona linking wants.

    Shared by the persona linker and the simulated-client seeder so the position-copy
    logic lives in exactly one place.
    """
    sample_name = _SAMPLE_CLIENT_NAMES[mandate]
    sample = (
        await session.execute(select(Client).where(Client.name == sample_name))
    ).scalar_one_or_none()
    if sample is None:
        raise RuntimeError(
            f"Sample client '{sample_name}' not found — run /admin/seed/portfolio first"
        )
    templates = list(
        (
            await session.execute(select(Position).where(Position.client_id == sample.id))
        ).scalars()
    )
    if not templates:
        raise RuntimeError(
            f"No positions for '{sample_name}' — run /admin/seed/portfolio first"
        )
    return await _reload_positions(
        session, client, templates, at_target_weight=at_target_weight
    )


async def _fetch_sample_positions(session: AsyncSession) -> dict[Mandate, list[Position]]:
    out: dict[Mandate, list[Position]] = {}
    for mandate, sample_name in _SAMPLE_CLIENT_NAMES.items():
        sample = (
            await session.execute(select(Client).where(Client.name == sample_name))
        ).scalar_one_or_none()
        if sample is None:
            raise RuntimeError(
                f"Sample client '{sample_name}' not found — run /admin/seed/portfolio first"
            )
        positions = list(
            (
                await session.execute(select(Position).where(Position.client_id == sample.id))
            ).scalars()
        )
        if not positions:
            raise RuntimeError(
                f"No positions for '{sample_name}' — run /admin/seed/portfolio first"
            )
        out[mandate] = positions
    return out


async def _reload_positions(
    session: AsyncSession,
    client: Client,
    templates: list[Position],
    *,
    at_target_weight: bool = False,
) -> int:
    # CASCADE positions.id → enriched_holdings.position_id removes enriched rows too.
    await session.execute(delete(Position).where(Position.client_id == client.id))

    new_positions: list[Position] = []
    for tmpl in templates:
        # at_target_weight pins the holding to its model weight (zero drift); otherwise
        # the Sample book's real drifted value is preserved. Fall back to current_chf
        # when a template carries no target (no-fallbacks: never invent a value).
        current_chf = (
            tmpl.target_chf
            if at_target_weight and tmpl.target_chf is not None
            else tmpl.current_chf
        )
        pos = Position(
            client_id=client.id,
            asset_class=tmpl.asset_class,
            sub_asset_class=tmpl.sub_asset_class,
            region=tmpl.region,
            industry_group=tmpl.industry_group,
            issuer=tmpl.issuer,
            security=tmpl.security,
            isin=tmpl.isin,
            valor=tmpl.valor,
            mic=tmpl.mic,
            yahoo=tmpl.yahoo,
            target_chf=tmpl.target_chf,
            current_chf=current_chf,
            quantity=tmpl.quantity,
        )
        session.add(pos)
        new_positions.append(pos)

    await session.flush()

    for pos in new_positions:
        tags = instrument_tags(pos.industry_group, pos.region)
        await session.execute(
            pg_insert(EnrichedHolding)
            .values(position_id=pos.id, tags=tags)
            .on_conflict_do_update(index_elements=["position_id"], set_={"tags": tags})
        )

    return len(new_positions)
