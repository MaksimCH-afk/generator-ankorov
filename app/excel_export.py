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
# Columns when the Article Language parameter is excluded from the export.
COLUMNS_NO_LANG = ["Link Q-ty", "URL", "Anchor", "Keyword"]

HEADER_FILL = PatternFill(start_color="843DCB", end_color="843DCB", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def _row_values(row: GeneratedRow, include_language: bool) -> list:
    if include_language:
        return [row.link_qty, row.url, row.anchor, row.article_language, row.keyword]
    return [row.link_qty, row.url, row.anchor, row.keyword]


def _write_sheet(ws, rows: list[GeneratedRow], include_language: bool) -> None:
    columns = COLUMNS if include_language else COLUMNS_NO_LANG
    ws.append(columns)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    for row in rows:
        ws.append(_row_values(row, include_language))

    # Auto-ish column widths.
    widths = [len(c) for c in columns]
    for row in rows:
        for i, value in enumerate(_row_values(row, include_language)):
            widths[i] = max(widths[i], len(str(value)))
    for i, width in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = min(width + 4, 70)
    ws.freeze_panes = "A2"


def build_workbook(sheets: dict[str, list[GeneratedRow]], include_language: bool = True) -> bytes:
    """Build one .xlsx file with the given ``sheet name -> rows`` mapping.

    When ``include_language`` is False the "Article Language" column is omitted
    from the output entirely.
    """
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=_safe_sheet_name(name))
        _write_sheet(ws, rows, include_language)
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
