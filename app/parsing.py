"""Parsing of uploaded frequency / project files (Excel or CSV) (§5)."""
from __future__ import annotations

import csv
import io

from openpyxl import load_workbook


def _rows_from_xlsx(content: bytes) -> list[list[str]]:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
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
    """Read an uploaded file into a list of string rows."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        return _rows_from_xlsx(content)
    return _rows_from_csv(content)


def _looks_like_header(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return any(w in joined for w in ("keyword", "ключ", "frequency", "частот", "freq"))


def parse_frequency(filename: str, content: bytes) -> list[tuple[str, float]]:
    """Parse a ``keyword | frequency`` table (§5.2).

    Returns ``[(keyword, frequency), ...]`` in original file order. A header row
    (if detected) is skipped. Rows without a keyword are ignored; a missing or
    non-numeric frequency defaults to 0.
    """
    rows = read_table(filename, content)
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
