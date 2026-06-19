"""Parsing of uploaded frequency / project files (Excel or CSV)."""
from __future__ import annotations

import csv
import io

from openpyxl import load_workbook


def _rows_from_xlsx(content: bytes) -> list[list[str]]:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    return _normalize_rows(ws)


def _normalize_rows(ws) -> list[list[str]]:
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append(["" if c is None else str(c).strip() for c in row])
    return rows


def _rows_from_csv(content: bytes) -> list[list[str]]:
    text = content.decode("utf-8-sig", errors="replace")
    # Sniff delimiter (comma / semicolon / tab) from the first non-empty line.
    sample = next((ln for ln in text.splitlines() if ln.strip()), "")
    delimiter = ","
    for cand in [";", "\t", ","]:
        if cand in sample:
            delimiter = cand
            break
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[c.strip() for c in row] for row in reader]


def read_table(filename: str, content: bytes) -> list[list[str]]:
    """Read an uploaded file into a list of string rows (first sheet for Excel)."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        return _rows_from_xlsx(content)
    return _rows_from_csv(content)


def _looks_like_header(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return any(w in joined for w in ("keyword", "ключ", "frequency", "freq", "частот", "volume", "объ", "vol"))


def rows_to_pairs(rows: list[list[str]]) -> list[tuple[str, float]]:
    """Turn raw string rows into ``[(keyword, frequency), ...]``.

    The first column is the keyword, the second (if any) the frequency/volume.
    A header row (if detected) is skipped. Rows without a keyword are ignored;
    a missing or non-numeric frequency defaults to 0.
    """
    out: list[tuple[str, float]] = []
    for i, cells in enumerate(rows):
        if not cells or not any(cells):
            continue
        if i == 0 and _looks_like_header(cells):
            continue
        keyword = cells[0].strip()
        if not keyword:
            continue
        freq = 0.0
        if len(cells) > 1:
            raw = cells[1].replace(",", ".").replace(" ", "")
            try:
                freq = float(raw)
            except ValueError:
                freq = 0.0
        out.append((keyword, freq))
    return out


def parse_frequency(filename: str, content: bytes) -> list[tuple[str, float]]:
    """Parse a single ``keyword | frequency`` table (first sheet for Excel)."""
    return rows_to_pairs(read_table(filename, content))


def parse_workbook_sheets(content: bytes) -> dict[str, list[tuple[str, float]]]:
    """Parse every sheet of an Excel workbook.

    Returns ``{sheet_name: [(keyword, frequency), ...]}``. Used by batch upload,
    where each sheet typically holds one project's частотка and the sheet name
    matches the project's domain or brand.
    """
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    result: dict[str, list[tuple[str, float]]] = {}
    for sheet_name in wb.sheetnames:
        result[sheet_name] = rows_to_pairs(_normalize_rows(wb[sheet_name]))
    return result
