"""CRM interaction notes loader (TASK-009, EPIC-02).

Ingests the four persona tabs from `SwissHacks CRM.xlsx` into the `clients` and
`interactions` tables. Safe to run multiple times: clients are get-or-created by
name; interactions are deleted-and-reloaded per client so a re-run reflects any
workbook edit.

Persona → mandate assignments follow Requirements §11 archetypes:
  Räber     → Defensive   (capital-preservation, tangible businesses)
  Schneider → Balanced    (note: "Global Balanced Growth mandate")
  Huber     → Balanced    (sustainable-agriculture; Defensive/Balanced archetype)
  Ammann    → Growth      (analytical, asymmetric-tail-risk focus)
"""

from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.enums import Mandate
from app.models.source import Client, Interaction
from app.xlsx import excel_serial_to_date, load_sheet

log = get_logger(__name__)

# (sheet_name, canonical_client_name, mandate)
_PERSONA_SHEETS: list[tuple[str, str, Mandate]] = [
    ("CRM Raeber",    "Eugen Räber",        Mandate.DEFENSIVE),
    ("CRM Schneider", "Hubertus Schneider",  Mandate.BALANCED),
    ("CRM Huber",     "Marius Huber",        Mandate.BALANCED),
    ("CRM Ammann",    "Julian Ammann",       Mandate.GROWTH),
]

_CRM_FILE = "SwissHacks CRM.xlsx"


async def _upsert_client(session: AsyncSession, name: str, mandate: Mandate) -> Client:
    """Return existing client by name, or create a new one."""
    result = await session.execute(select(Client).where(Client.name == name))
    client = result.scalar_one_or_none()
    if client is None:
        client = Client(name=name, mandate=mandate)
        session.add(client)
        await session.flush()  # assign PK before FK inserts
        log.info("crm.client_created", name=name, mandate=mandate.value)
    else:
        log.info("crm.client_found", name=name, id=str(client.id))
    return client


async def load_crm(session: AsyncSession, data_dir: str | Path) -> dict[str, int]:
    """Load all four persona CRM sheets into the DB.

    Returns a dict of {client_name: interaction_count} for logging/response.
    Commits a single transaction covering all four personas.
    """
    workbook_path = Path(data_dir) / _CRM_FILE
    counts: dict[str, int] = {}

    for sheet_name, client_name, mandate in _PERSONA_SHEETS:
        rows = load_sheet(workbook_path, sheet_name)
        client = await _upsert_client(session, client_name, mandate)

        # Delete-and-reload makes the operation idempotent: a re-run reflects
        # any workbook edit rather than silently keeping stale rows.
        await session.execute(delete(Interaction).where(Interaction.client_id == client.id))

        interactions = []
        for row in rows:
            date_val = None
            if row.get("Date"):
                try:
                    date_val = excel_serial_to_date(float(row["Date"]))
                except (ValueError, TypeError):
                    pass  # non-date numeric cell — leave as None

            interactions.append(
                Interaction(
                    client_id=client.id,
                    date=date_val,
                    medium=row.get("Medium"),
                    rm_name=row.get("RM Name"),
                    client_contact=row.get("Client Contact"),
                    note=row.get("Note"),
                )
            )

        session.add_all(interactions)
        counts[client_name] = len(interactions)
        log.info(
            "crm.sheet_loaded",
            sheet=sheet_name,
            client=client_name,
            rows=len(interactions),
        )

    await session.commit()
    log.info("crm.load_complete", counts=counts)
    return counts
