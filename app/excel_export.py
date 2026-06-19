"""Excel (and batch ZIP) export (§6)."""
from __future__ import annotations

import io
import re
import zipfile

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .generator import GeneratedRow

COLUMNS = ["Link Q-ty", "URL", "Anchor", "Article Language", "Keyword"]

HEADER_FILL = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def _write_sheet(ws, rows: list[GeneratedRow]) -> None:
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    for row in rows:
        ws.append([row.link_qty, row.url, row.anchor, row.article_language, row.keyword])

    # Auto-ish column widths.
    widths = [len(c) for c in COLUMNS]
    for row in rows:
        for i, value in enumerate([row.link_qty, row.url, row.anchor, row.article_language, row.keyword]):
            widths[i] = max(widths[i], len(str(value)))
    for i, width in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = min(width + 4, 70)
    ws.freeze_panes = "A2"


def build_workbook(sheets: dict[str, list[GeneratedRow]]) -> bytes:
    """Build one .xlsx file with the given ``sheet name -> rows`` mapping."""
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=_safe_sheet_name(name))
        _write_sheet(ws, rows)
    if not wb.sheetnames:  # never leave an empty workbook
        wb.create_sheet(title="Empty")
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _safe_sheet_name(name: str) -> str:
    """Excel sheet names: max 31 chars, no ``[]:*?/\\``."""
    cleaned = re.sub(r"[\[\]:\*\?/\\]", "-", name)
    return cleaned[:31] or "Sheet"


def safe_filename(url: str) -> str:
    """Turn a URL into a filesystem-safe .xlsx base name."""
    name = re.sub(r"^https?://", "", url).strip("/")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return (name or "project") + ".xlsx"


def build_zip(files: dict[str, bytes]) -> bytes:
    """Bundle ``filename -> bytes`` into a ZIP archive (§6 batch)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    return buffer.getvalue()
