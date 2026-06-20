"""Unit checks for the stdlib XLSX parser (TASK-007, EPIC-02).

Anchored to stable, documented values from the two provided workbooks
(Requirements §10) so a regression in shared-string resolution, sheet mapping,
or column alignment fails loudly. Data files live at the repo root `data/`,
resolved relative to this test regardless of the pytest invocation directory.
"""

import os
from datetime import date
from pathlib import Path

import pytest

from app.xlsx import excel_serial_to_date, load_sheet, sheet_names

_CRM_NAME = "SwissHacks CRM.xlsx"
_PORTFOLIO_NAME = "SwissHacks Portfolio Construction.xlsx"


def _find_data_dir() -> Path:
    """Locate the `data/` workbook dir across host and container layouts.

    Host: tests live at `backend/tests/`, data at the repo root (`parents[2]`).
    Container: `./data` is mounted at `/app/data`, i.e. `parents[1]/data`.
    `WEALTH_DATA_DIR` overrides both.
    """
    here = Path(__file__).resolve()
    candidates = [
        Path(os.environ["WEALTH_DATA_DIR"]) if os.environ.get("WEALTH_DATA_DIR") else None,
        here.parents[2] / "data",
        here.parents[1] / "data",
        Path("/app/data"),
    ]
    for candidate in candidates:
        if candidate and (candidate / _CRM_NAME).exists():
            return candidate
    raise FileNotFoundError(f"workbooks not found; checked {[str(c) for c in candidates if c]}")


_DATA = _find_data_dir()
_CRM = _DATA / _CRM_NAME
_PORTFOLIO = _DATA / _PORTFOLIO_NAME


def test_crm_sheet_names_in_tab_order():
    assert sheet_names(_CRM) == [
        "CRM Raeber",
        "CRM Schneider",
        "CRM Huber",
        "CRM Ammann",
    ]


def test_crm_schneider_header_and_first_row():
    rows = load_sheet(_CRM, "CRM Schneider")
    assert list(rows[0].keys()) == ["Date", "Medium", "RM Name", "Client Contact", "Note"]
    first = rows[0]
    assert first["Medium"] == "Physical Meeting"
    assert first["RM Name"] == "Thomas Keller"
    assert first["Client Contact"] == "Hubertus Schneider"
    # Date column stays a raw serial — the parser does not coerce types.
    assert first["Date"] == "45026"


def test_portfolio_sheets_present():
    names = sheet_names(_PORTFOLIO)
    assert len(names) == 10
    for expected in (
        "Portfolio Strategies",
        "CIO Recommendation List",
        "Sample Portfolio Defensive",
        "Sample Portfolio Balanced",
        "Sample Portfolio Growth",
    ):
        assert expected in names


def test_cio_recommendation_list_row_count():
    # 172 data rows (173 incl. header) per Requirements §10.2.
    rows = load_sheet(_PORTFOLIO, "CIO Recommendation List")
    assert len(rows) == 172


def test_excel_serial_to_date_roundtrip():
    # Schneider's first note serial → the date Excel displays.
    assert excel_serial_to_date(45026) == date(2023, 4, 10)


def test_missing_sheet_raises_keyerror():
    with pytest.raises(KeyError):
        load_sheet(_CRM, "Nonexistent Sheet")
