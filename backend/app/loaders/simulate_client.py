"""Simulated-client onboarding seeder (TASK-064, EPIC-10).

Onboards a single canned demo client the way a brand-new customer would arrive:
notes + a mandate, and no holdings yet. The pipeline then produces the cleanest
possible before/after for the personalisation thesis (TASK-065):

  before (house model) : the mandate's Sample portfolio — the CIO default instrument
                         per slot, no drift — copied onto the client as owned positions.
  after  (personalised): the existing fit + swap engine, run against the client's OWN
                         DNA, proposes a best-fit CIO-BUY for each slot whose default
                         instrument conflicts with the client's values.

Nothing is invented (grounding · no-fallbacks): baseline holdings are real Sample
positions and the personalised "after" lives in `swap_proposals` — `positions` are
never mutated, so per-sub-asset-class weights are identical by construction. That
structural fact is the mandate-neutral proof; `find_weight_neutrality_violations`
re-checks it at runtime and the seeder raises if it is ever broken.

DNA is extracted by the LLM (Phoeniqs) via `extract_dna`, so exclusions/tilts carry
real source citations. If the LLM is unreachable the seeder fails loudly rather than
writing empty DNA.

Called from POST /admin/seed/simulate-client. Requires /admin/seed/portfolio first.
Idempotent: re-running wipes the sim client's interactions/positions/DNA and rebuilds.
"""

import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.loaders.dna import extract_dna
from app.loaders.fit import compute_fit
from app.loaders.persona_portfolio import copy_sample_positions
from app.loaders.swap import compute_swaps
from app.logging import get_logger
from app.models.derived import SwapProposal
from app.models.enums import Mandate
from app.models.source import CIORecommendation, Client, Interaction, Position

log = get_logger(__name__)

# The canned onboarding data. Modelled on the persona narrative style: a values-led
# Balanced client whose fossil-fuel red line + sustainability tilt the Sample Balanced
# book (which holds Energy names tagged `fossil`/`fossil-fuel`) clearly triggers — so
# the "after" yields a visible, citeable swap. The [SIMULATED] prefix keeps the name
# from colliding with the personas, the Sample clients, or the [SYNTHETIC] scale set.
_RM_NAME = "Sandra Keller"
_CLIENT_CONTACT = "Clara Bauer"

_SIM_CLIENT: dict = {
    "name": "[SIMULATED] Clara Bauer",
    "mandate": Mandate.BALANCED,
    "notes": [
        {
            "date": date(2026, 1, 14),
            "medium": "Meeting",
            "note": (
                "Onboarding meeting with Clara Bauer, founder of a Zurich design "
                "studio she sold last year. Opening a Balanced mandate. She was "
                "emphatic that she will not own oil, gas or coal companies under any "
                "circumstances — she divested her previous bank portfolio of fossil "
                "fuels two years ago and does not want to see them return. Asked us "
                "to build the portfolio around her climate convictions."
            ),
        },
        {
            "date": date(2026, 2, 20),
            "medium": "Call",
            "note": (
                "Follow-up call. Clara reiterated her preference to tilt the portfolio "
                "towards sustainable and clean-energy themes wherever possible. She is "
                "comfortable with the Balanced risk profile and does not want to change "
                "the strategy — her point is purely about which companies we hold, not "
                "the asset allocation."
            ),
        },
        {
            "date": date(2026, 3, 18),
            "medium": "Email",
            "note": (
                "Clara forwarded an article on renewable-energy infrastructure and "
                "asked whether her holdings could lean that way. Confirmed again that "
                "fossil-fuel exposure is a hard exclusion for her."
            ),
        },
    ],
}


def find_weight_neutrality_violations(
    pairs: list[tuple[str | None, str | None, str | None, str | None]],
) -> list[dict]:
    """Return slot mismatches between a held position and its proposed swap candidate.

    Each pair is ``(holding_sub_asset_class, holding_industry_group,
    candidate_sub_asset_class, candidate_industry_group)``. A personalised swap must
    preserve the slot — same sub-asset-class (weight invariant, E1/E8) and same
    industry group (sector-risk neutral, E3) — so any pair where either differs would
    shift the sub-asset-class weights and is a mandate-neutrality violation.

    Pure function (no I/O) so it is unit-testable without a database.
    """
    violations: list[dict] = []
    for h_sac, h_ig, c_sac, c_ig in pairs:
        if h_sac != c_sac or h_ig != c_ig:
            violations.append(
                {
                    "holding_sub_asset_class": h_sac,
                    "holding_industry_group": h_ig,
                    "candidate_sub_asset_class": c_sac,
                    "candidate_industry_group": c_ig,
                }
            )
    return violations


async def seed_simulated_client(session: AsyncSession) -> dict:
    """Onboard the canned simulated client and build its model + personalised views.

    Returns row counts for each pipeline step plus the new client_id. Raises
    RuntimeError (→ 409) if the Sample portfolios have not been seeded yet.
    """
    spec = _SIM_CLIENT
    name: str = spec["name"]
    mandate: Mandate = spec["mandate"]

    client = await _get_or_create_client(session, name, mandate)

    # Delete-and-reload interactions so a re-run reflects any edit to the canned data.
    await session.execute(delete(Interaction).where(Interaction.client_id == client.id))
    for note in spec["notes"]:
        session.add(
            Interaction(
                client_id=client.id,
                date=note["date"],
                medium=note["medium"],
                rm_name=_RM_NAME,
                client_contact=_CLIENT_CONTACT,
                note=note["note"],
            )
        )

    # House-model baseline: the mandate's Sample holdings pinned to CIO target weights
    # so the book has zero drift — the contrast is then purely instrument selection.
    positions = await copy_sample_positions(
        session, client, mandate, at_target_weight=True
    )

    # Persist client + interactions + baseline before the derived loaders run
    # (each of which commits per client internally).
    await session.commit()
    log.info(
        "simulate_client.baseline_ready",
        client=name,
        mandate=mandate.value,
        positions=positions,
        notes=len(spec["notes"]),
    )

    # Personalisation pipeline, scoped to this client only.
    dna = await extract_dna(session, client_id=client.id)  # LLM (Phoeniqs) + citations
    fit = await compute_fit(session, client_id=client.id)
    swap = await compute_swaps(session, client_id=client.id)

    await _assert_weight_neutral(session, client)

    result = {
        "client_id": str(client.id),
        "name": name,
        "mandate": mandate.value,
        "interactions": len(spec["notes"]),
        "positions": positions,
        "dna": dna,
        "fit": fit,
        "swap": swap,
    }
    log.info("simulate_client.complete", **{k: v for k, v in result.items() if k != "client_id"})
    return result


async def _get_or_create_client(
    session: AsyncSession, name: str, mandate: Mandate
) -> Client:
    client = (
        await session.execute(select(Client).where(Client.name == name))
    ).scalar_one_or_none()
    if client is None:
        client = Client(name=name, mandate=mandate)
        session.add(client)
        await session.flush()  # assign PK before FK inserts
        log.info("simulate_client.client_created", name=name)
    return client


async def _assert_weight_neutral(session: AsyncSession, client: Client) -> None:
    """Re-check that every proposed swap preserves its slot (mandate-neutral proof)."""
    rows = (
        await session.execute(
            select(
                Position.sub_asset_class,
                Position.industry_group,
                CIORecommendation.sub_asset_class,
                CIORecommendation.industry_group,
            )
            .select_from(SwapProposal)
            .join(Position, SwapProposal.holding_id == Position.id)
            .join(CIORecommendation, CIORecommendation.isin == SwapProposal.candidate_isin)
            .where(
                Position.client_id == client.id,
                SwapProposal.candidate_isin.isnot(None),
            )
        )
    ).all()

    violations = find_weight_neutrality_violations([tuple(r) for r in rows])
    if violations:
        # Fix at source rather than ship a portfolio whose weights silently drifted.
        raise RuntimeError(
            f"Weight-neutrality violated for '{client.name}': {violations}"
        )
    log.info("simulate_client.weight_neutral_ok", client=client.name, checked=len(rows))
