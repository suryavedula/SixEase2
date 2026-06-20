"""Portfolio workbook ingestion (TASK-008, EPIC-02).

Loads mandate strategies, CIO recommendations, seed clients, and positions from
`data/SwissHacks Portfolio Construction.xlsx`. Each operation is idempotent:
mandate strategies upsert by (mandate, sub_asset_class); seed clients are
get-or-created by name; positions and CIO rows are deleted-and-reloaded.

Seed clients are named "Sample Defensive/Balanced/Growth" — separate from the
four CRM personas loaded by TASK-009. Downstream tasks (drift, swap engine)
query positions via client_id and mandate rather than by name.

Called from POST /admin/seed/portfolio via app.routers.admin.
"""

from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.enums import CIORating, Mandate
from app.models.source import CIORecommendation, Client, MandateStrategy, Position
from app.xlsx import excel_serial_to_date, load_workbook

log = get_logger(__name__)

_WORKBOOK = "SwissHacks Portfolio Construction.xlsx"

_MANDATE_PCT_COLS: dict[Mandate, str] = {
    Mandate.DEFENSIVE: "Def %",
    Mandate.BALANCED:  "Balanced %",
    Mandate.GROWTH:    "Growth %",
}

_PORTFOLIO_SHEETS: dict[Mandate, str] = {
    Mandate.DEFENSIVE: "Sample Portfolio Defensive",
    Mandate.BALANCED:  "Sample Portfolio Balanced",
    Mandate.GROWTH:    "Sample Portfolio Growth",
}

_SEED_CLIENT_NAMES: dict[Mandate, str] = {
    Mandate.DEFENSIVE: "Sample Defensive",
    Mandate.BALANCED:  "Sample Balanced",
    Mandate.GROWTH:    "Sample Growth",
}


async def load_portfolio(session: AsyncSession, data_dir: str | Path) -> dict[str, int]:
    """Load all portfolio tables from the workbook. Single commit at the end.

    Returns row counts per table: mandate_strategies, clients, positions,
    cio_recommendations.
    """
    wb = load_workbook(Path(data_dir) / _WORKBOOK)

    n_strategies = await _load_mandate_strategies(session, wb["Portfolio Strategies"])
    n_clients, n_positions = await _load_sample_portfolios(session, wb)
    held_isins = await _collect_held_isins(session)
    n_cio = await _load_cio_recommendations(
        session, wb["CIO Recommendation List"], held_isins
    )

    await session.commit()
    log.info(
        "portfolio.load_complete",
        mandate_strategies=n_strategies,
        clients=n_clients,
        positions=n_positions,
        cio_recommendations=n_cio,
    )
    return {
        "mandate_strategies": n_strategies,
        "clients": n_clients,
        "positions": n_positions,
        "cio_recommendations": n_cio,
    }


async def _load_mandate_strategies(session: AsyncSession, rows: list[dict]) -> int:
    """Upsert 12 sub-asset-class rows × 3 mandates = 36 records.

    Uses the existing unique index on (mandate, sub_asset_class) as the
    conflict target so re-runs update the weight rather than erroring.
    """
    count = 0
    for row in rows:
        sac = row.get("Sub-Asset Class")
        if not sac:
            continue  # skip blank rows / section-total rows
        for mandate, col in _MANDATE_PCT_COLS.items():
            raw = row.get(col)
            if raw is None:
                continue
            stmt = (
                pg_insert(MandateStrategy)
                .values(
                    mandate=mandate,
                    sub_asset_class=sac,
                    target_weight=float(raw),
                )
                .on_conflict_do_update(
                    index_elements=["mandate", "sub_asset_class"],
                    set_={"target_weight": float(raw)},
                )
            )
            await session.execute(stmt)
            count += 1
    log.info("portfolio.mandate_strategies_loaded", count=count)
    return count


async def _get_or_create_client(
    session: AsyncSession, name: str, mandate: Mandate
) -> Client:
    result = await session.execute(select(Client).where(Client.name == name))
    client = result.scalar_one_or_none()
    if client is None:
        client = Client(name=name, mandate=mandate)
        session.add(client)
        await session.flush()  # assign PK before downstream FK inserts
        log.info("portfolio.client_created", name=name, mandate=mandate.value)
    else:
        log.info("portfolio.client_found", name=name, id=str(client.id))
    return client


async def _load_sample_portfolios(
    session: AsyncSession, wb: dict[str, list[dict]]
) -> tuple[int, int]:
    """Upsert 3 seed clients; delete-and-reload their positions."""
    client_count = 0
    total_positions = 0

    for mandate, client_name in _SEED_CLIENT_NAMES.items():
        client = await _get_or_create_client(session, client_name, mandate)
        client_count += 1

        # Delete-and-reload makes the operation idempotent on re-run
        await session.execute(delete(Position).where(Position.client_id == client.id))

        sheet_positions = 0
        for row in wb[_PORTFOLIO_SHEETS[mandate]]:
            if not any(row.values()):
                continue
            session.add(
                Position(
                    client_id=client.id,
                    asset_class=row.get("Asset Class"),
                    sub_asset_class=row.get("Sub-Asset Class"),
                    region=row.get("Region"),
                    industry_group=row.get("Industry Group"),
                    issuer=row.get("Issuer / Asset"),
                    security=row.get("Security / Details"),
                    isin=row.get("ISIN") or None,
                    target_chf=_to_decimal(row.get("Target (CHF)")),
                    current_chf=_to_decimal(row.get("Current (CHF)")),
                    valor=row.get("Valor") or None,
                    mic=row.get("MIC") or None,
                    yahoo=row.get("Yahoo Ticker") or None,
                    # quantity left NULL: bonds face÷100 computed by TASK-026
                )
            )
            sheet_positions += 1

        total_positions += sheet_positions
        log.info(
            "portfolio.positions_loaded",
            client=client_name,
            mandate=mandate.value,
            rows=sheet_positions,
        )

    return client_count, total_positions


async def _collect_held_isins(session: AsyncSession) -> set[str]:
    """ISINs currently in positions — used to flag CIO BUY swap candidates."""
    result = await session.execute(
        select(Position.isin).where(Position.isin.isnot(None))
    )
    return {row[0] for row in result}


async def _load_cio_recommendations(
    session: AsyncSession, rows: list[dict], held_isins: set[str]
) -> int:
    """Delete-and-reload 172 CIO rows; set is_swap_candidate for BUY-not-held."""
    await session.execute(delete(CIORecommendation))

    count = 0
    for row in rows:
        raw_rating = (row.get("Rating") or "").strip().upper()
        try:
            rating = CIORating[raw_rating]
        except KeyError:
            continue  # blank / unrecognised rating row

        isin = row.get("ISIN") or None
        # BUY rows not currently held in any sample portfolio are swap candidates
        is_swap = rating == CIORating.BUY and (isin is None or isin not in held_isins)

        session.add(
            CIORecommendation(
                rating=rating,
                rating_since=_to_date(row.get("Rating Since")),
                as_of=_to_date(row.get("As Of")),
                asset_class=row.get("Asset Class"),
                sub_asset_class=row.get("Sub-Asset Class"),
                region=row.get("Region"),
                industry_group=row.get("Industry Group"),
                issuer=row.get("Issuer / Asset"),
                security=row.get("Security / Details"),
                isin=isin,
                cio_view=row.get("CIO View"),
                valor=row.get("Valor") or None,
                mic=row.get("MIC") or None,
                yahoo=row.get("Yahoo Ticker") or None,
                is_swap_candidate=is_swap,
            )
        )
        count += 1

    log.info("portfolio.cio_recommendations_loaded", count=count)
    return count


def _to_decimal(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return excel_serial_to_date(float(value))
    except (ValueError, TypeError):
        return None
