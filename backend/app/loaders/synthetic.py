"""Synthetic client generator (TASK-011, EPIC-02).

Generates 100 reproducible synthetic clients (4 archetypes × 25) by copying
positions verbatim from the three Sample mandate portfolios loaded by TASK-008.
DNA is authored directly from the archetype template + seeded variation — no
LLM extraction. The [SYNTHETIC] prefix (G6) makes every row unambiguous.

Called from POST /admin/seed/synthetic via app.routers.admin.
"""

import random

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import ClientDNA, EnrichedHolding
from app.models.enums import Mandate
from app.models.source import Client, Position
from app.tags import instrument_tags

log = get_logger(__name__)

SEED = 42
N_PER_ARCHETYPE = 25

ARCHETYPES: list[dict] = [
    {
        "label": "Defensive Value",
        "mandate": Mandate.DEFENSIVE,
        "base_exclusions": ["us-tech"],
        "base_tilts": ["tech"],
        "optional_exclusions": ["fossil"],
        "optional_tilts": [],
    },
    {
        "label": "Purpose ESG",
        "mandate": Mandate.BALANCED,
        "base_exclusions": ["fossil", "fossil-fuel", "deforestation-risk"],
        "base_tilts": ["sustainability"],
        "optional_exclusions": ["labour-risk"],
        "optional_tilts": [],
    },
    {
        "label": "Corporate Reputation",
        "mandate": Mandate.GROWTH,
        "base_exclusions": ["labour-risk"],
        "base_tilts": ["luxury"],
        "optional_exclusions": ["deforestation-risk"],
        "optional_tilts": [],
    },
    {
        "label": "Personal Cause Health",
        "mandate": Mandate.BALANCED,
        "base_exclusions": ["pharma"],
        "base_tilts": ["neuro-research"],
        "optional_exclusions": [],
        "optional_tilts": ["sustainability"],
    },
]

_SAMPLE_CLIENT_NAMES: dict[Mandate, str] = {
    Mandate.DEFENSIVE: "Sample Defensive",
    Mandate.BALANCED: "Sample Balanced",
    Mandate.GROWTH: "Sample Growth",
}

_STYLE_PROFILES = ["data-driven", "values-led", "relationship-first", "formal"]


async def load_synthetic_clients(session: AsyncSession) -> dict[str, int]:
    """Generate 100 synthetic clients with positions and DNA. Single commit at end.

    Returns row counts: clients, positions, dna_rows, enriched_holdings.
    Raises RuntimeError if the sample portfolios haven't been seeded yet.
    """
    rng = random.Random(SEED)

    sample_positions = await _fetch_sample_positions(session)

    total_clients = 0
    total_positions = 0
    total_dna = 0
    total_enriched = 0

    for archetype in ARCHETYPES:
        label: str = archetype["label"]
        mandate: Mandate = archetype["mandate"]
        templates = sample_positions[mandate]

        for i in range(1, N_PER_ARCHETYPE + 1):
            name = f"[SYNTHETIC] {label} #{i:03d}"
            client = await _get_or_create_client(session, name, mandate)
            total_clients += 1

            n_pos, n_enr = await _reload_positions(session, client, templates)
            total_positions += n_pos
            total_enriched += n_enr

            await _upsert_dna(session, client, archetype, rng)
            total_dna += 1

        log.info("synthetic.archetype_loaded", archetype=label, count=N_PER_ARCHETYPE)

    await session.commit()
    log.info(
        "synthetic.load_complete",
        clients=total_clients,
        positions=total_positions,
        dna_rows=total_dna,
        enriched_holdings=total_enriched,
    )
    return {
        "clients": total_clients,
        "positions": total_positions,
        "dna_rows": total_dna,
        "enriched_holdings": total_enriched,
    }


async def _fetch_sample_positions(session: AsyncSession) -> dict[Mandate, list[Position]]:
    out: dict[Mandate, list[Position]] = {}
    for mandate, sample_name in _SAMPLE_CLIENT_NAMES.items():
        result = await session.execute(select(Client).where(Client.name == sample_name))
        sample_client = result.scalar_one_or_none()
        if sample_client is None:
            raise RuntimeError(
                f"Sample client '{sample_name}' not found — run /admin/seed/portfolio first"
            )
        pos_result = await session.execute(
            select(Position).where(Position.client_id == sample_client.id)
        )
        positions = list(pos_result.scalars())
        if not positions:
            raise RuntimeError(
                f"No positions for '{sample_name}' — run /admin/seed/portfolio first"
            )
        out[mandate] = positions
    return out


async def _get_or_create_client(
    session: AsyncSession, name: str, mandate: Mandate
) -> Client:
    result = await session.execute(select(Client).where(Client.name == name))
    client = result.scalar_one_or_none()
    if client is None:
        client = Client(name=name, mandate=mandate)
        session.add(client)
        await session.flush()
        log.info("synthetic.client_created", name=name)
    return client


async def _reload_positions(
    session: AsyncSession, client: Client, templates: list[Position]
) -> tuple[int, int]:
    # CASCADE on positions.id → enriched_holdings.position_id handles deletion of enriched rows
    await session.execute(delete(Position).where(Position.client_id == client.id))

    new_positions: list[Position] = []
    for tmpl in templates:
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
            current_chf=tmpl.current_chf,
            quantity=tmpl.quantity,
        )
        session.add(pos)
        new_positions.append(pos)

    await session.flush()

    for pos in new_positions:
        tags = instrument_tags(pos.industry_group, pos.region)
        stmt = (
            pg_insert(EnrichedHolding)
            .values(position_id=pos.id, tags=tags)
            .on_conflict_do_update(
                index_elements=["position_id"],
                set_={"tags": tags},
            )
        )
        await session.execute(stmt)

    return len(new_positions), len(new_positions)


async def _upsert_dna(
    session: AsyncSession,
    client: Client,
    archetype: dict,
    rng: random.Random,
) -> None:
    exclusions = [
        {"tag": t, "source": "synthetic", "confidence": 1.0}
        for t in archetype["base_exclusions"]
    ]
    for t in archetype["optional_exclusions"]:
        if rng.random() < 0.5:
            exclusions.append({"tag": t, "source": "synthetic", "confidence": 1.0})

    tilts = [
        {"tag": t, "source": "synthetic", "confidence": 1.0}
        for t in archetype["base_tilts"]
    ]
    for t in archetype["optional_tilts"]:
        if rng.random() < 0.5:
            tilts.append({"tag": t, "source": "synthetic", "confidence": 1.0})

    style = rng.choice(_STYLE_PROFILES)

    stmt = (
        pg_insert(ClientDNA)
        .values(
            client_id=client.id,
            mandate=archetype["mandate"],
            exclusions=exclusions,
            tilts=tilts,
            style_profile={"tone": style},
        )
        .on_conflict_do_update(
            index_elements=["client_id"],
            set_={
                "mandate": archetype["mandate"],
                "exclusions": exclusions,
                "tilts": tilts,
                "style_profile": {"tone": style},
            },
        )
    )
    await session.execute(stmt)
