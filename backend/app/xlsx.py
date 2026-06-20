"""Stdlib XLSX reader (TASK-007, EPIC-02).

Reads the provided `.xlsx` workbooks with **only the standard library** — `zipfile`
+ `xml.etree` — because `pandas`/`openpyxl` are a hard "no" for this project
(CLAUDE.md). An `.xlsx` is a zip of XML parts; we resolve shared strings, map sheet
names to their part via the workbook relationships, and return each sheet as a list
of header-keyed row dicts.

Synchronous and dependency-free by design (mirrors the flat-module shape of
`app/storage.py`): parsing is CPU-bound and called from setup/seed paths, never the
hot request loop. Consumers (CRM DNA extraction, portfolio/drift engine, CIO swap
universe — Requirements §10.4) reuse `load_sheet`/`load_workbook` unchanged.

The parser stays data-semantics-free: it returns raw cell text and never coerces
types. Excel stores dates as integer serials (Requirements §10.3); callers convert
the columns they know are dates via `excel_serial_to_date` — we do NOT blanket
guess, since plenty of legitimate numeric columns (amounts, valors) would collide.
"""

import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from app.logging import get_logger

log = get_logger(__name__)

# SpreadsheetML main namespace (worksheets + sharedStrings) and the relationships
# namespace used in workbook.xml (`r:id`) and the .rels parts.
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# Excel's day-zero. 1899-12-30 (not 31st) absorbs the legacy 1900-leap-year bug, so
# serial 45026 → 2023-04-10 matches what Excel displays.
_EXCEL_EPOCH = date(1899, 12, 30)


def excel_serial_to_date(serial: float) -> date:
    """Convert an Excel date serial number to a `date` (Requirements §10.3).

    Caller's responsibility to apply this only to columns it knows are dates
    (e.g. CRM `Date`, CIO `Rating Since` / `As Of`).
    """
    return _EXCEL_EPOCH + timedelta(days=int(serial))


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """Resolve `xl/sharedStrings.xml` into an index-ordered list of strings.

    A cell with `t="s"` stores an integer index into this table. Each `<si>` may
    hold a single `<t>` or several `<t>` runs (rich text) — we concatenate them.
    """
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{_NS}t")) for si in root]


def _sheet_targets(zf: zipfile.ZipFile) -> dict[str, str]:
    """Map sheet display name → zip path, preserving workbook (tab) order.

    Resolved via `xl/workbook.xml` (`<sheet name= r:id=>`) joined to
    `xl/_rels/workbook.xml.rels` — never the positional `sheetN.xml` order, which
    is not guaranteed to match the tab order.
    """
    rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.get("Id"): rel.get("Target") for rel in rels_root.iter(f"{_PKG_REL_NS}Relationship")
    }

    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
    targets: dict[str, str] = {}
    for sheet in wb_root.iter(f"{_NS}sheet"):
        name = sheet.get("name")
        rid = sheet.get(f"{_REL_NS}id")
        target = rel_targets.get(rid)
        if name is None or target is None:
            continue
        # Targets are workbook-relative (e.g. "worksheets/sheet2.xml"); make them
        # package-absolute. Some producers emit a leading "/".
        targets[name] = "xl/" + target.lstrip("/") if not target.startswith("/") else target.lstrip("/")
    return targets


def _col_index(ref: str | None) -> int:
    """Zero-based column index from a cell reference's letter part (`B7` → 1).

    Blank cells are simply absent from the XML, so we key off the `r` ref rather
    than positional order — otherwise gaps would shift every later column.
    """
    if not ref:
        return 0
    letters = "".join(ch for ch in ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def _cell_value(cell: ET.Element, shared: list[str]) -> str | None:
    """Resolve a `<c>` cell to its string value (or None if empty)."""
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        inline = cell.find(f"{_NS}is")
        if inline is None:
            return None
        return "".join(t.text or "" for t in inline.iter(f"{_NS}t")) or None

    value = cell.find(f"{_NS}v")
    if value is None or value.text is None:
        return None
    if cell_type == "s":
        return shared[int(value.text)]
    # "str" (formula result), numeric, boolean — return raw text; no coercion.
    return value.text


def _parse_sheet(zf: zipfile.ZipFile, target: str, shared: list[str]) -> list[dict]:
    """Parse one worksheet part into header-keyed row dicts.

    The first non-empty row is the header. Later rows pad missing columns with
    None (via the cell `r` ref) so sparse rows align with the header.
    """
    ws_root = ET.fromstring(zf.read(target))
    rows_iter = ws_root.iter(f"{_NS}row")

    header: list[str] = []
    for row in rows_iter:
        cells = list(row.iter(f"{_NS}c"))
        if not cells:
            continue
        width = max(_col_index(c.get("r")) for c in cells) + 1
        values: list[str | None] = [None] * width
        for c in cells:
            values[_col_index(c.get("r"))] = _cell_value(c, shared)
        if any(v is not None for v in values):
            header = [str(v) if v is not None else f"col{i}" for i, v in enumerate(values)]
            break

    out: list[dict] = []
    for row in rows_iter:
        cells = list(row.iter(f"{_NS}c"))
        if not cells:
            continue
        record: dict = {h: None for h in header}
        has_value = False
        for c in cells:
            col = _col_index(c.get("r"))
            if col >= len(header):
                continue  # data past the header width — ignore stray cells
            val = _cell_value(c, shared)
            record[header[col]] = val
            has_value = has_value or val is not None
        if has_value:
            out.append(record)
    return out


def sheet_names(path: str | Path) -> list[str]:
    """Return the workbook's sheet names in tab order."""
    with zipfile.ZipFile(path) as zf:
        return list(_sheet_targets(zf).keys())


def load_sheet(path: str | Path, sheet: str) -> list[dict]:
    """Load one named sheet into a list of header-keyed row dicts.

    Raises `KeyError` if the sheet name is not present in the workbook.
    """
    with zipfile.ZipFile(path) as zf:
        targets = _sheet_targets(zf)
        if sheet not in targets:
            raise KeyError(f"sheet {sheet!r} not found; available: {list(targets)}")
        shared = _read_shared_strings(zf)
        rows = _parse_sheet(zf, targets[sheet], shared)
    log.info("xlsx.parsed", path=str(path), sheet=sheet, rows=len(rows))
    return rows


def load_workbook(path: str | Path) -> dict[str, list[dict]]:
    """Load every sheet into `{sheet_name: rows}`, preserving tab order."""
    with zipfile.ZipFile(path) as zf:
        targets = _sheet_targets(zf)
        shared = _read_shared_strings(zf)
        workbook = {name: _parse_sheet(zf, target, shared) for name, target in targets.items()}
    log.info(
        "xlsx.parsed",
        path=str(path),
        sheets=len(workbook),
        rows={name: len(rows) for name, rows in workbook.items()},
    )
    return workbook
