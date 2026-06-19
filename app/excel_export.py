"""Excel (and batch ZIP) export."""
from __future__ import annotations

import io
import re
import zipfile

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .generator import GeneratedRow, domain_of

# Output columns of the final TЗ (see reference file). One row = one link.
BASE_COLUMNS = [
    "Sprint",
    "SEO Specialist",
    "Project",
    "Project Url",
    "URL Type",
    "Link Type",
    "Anchor Type",
    "Anchor",
    "Keyword",
]
LANG_COLUMN = "Article Language"

# Match the reference file: black header row, white bold text, black body text.
HEADER_FILL = PatternFill(start_color="000000", end_color="000000", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
BODY_FONT = Font(color="000000")

INTERNAL_SHEET = "Внутренние страницы"


def _line(row: GeneratedRow, sprint: str, seo: str, url_type: str,
          include_language: bool, language: str) -> list:
    """Build one output line. Link Type / Anchor Type / Keyword stay empty."""
    line = [
        sprint,
        seo,
        domain_of(row.url),   # Project: bare domain (site.com)
        row.url,              # Project Url: the page we link to
        url_type,
        "",                   # Link Type — empty
        "",                   # Anchor Type — empty
        row.anchor,           # Anchor — as computed
        "",                   # Keyword — empty
    ]
    if include_language:
        line.append(language)
    return line


def _write_sheet(ws, rows: list[GeneratedRow], columns: list[str], sprint: str, seo: str,
                 url_type: str, include_language: bool, language: str) -> None:
    ws.append(columns)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    # One row per link: repeat each anchor by its link quantity.
    for row in rows:
        line = _line(row, sprint, seo, url_type, include_language, language)
        for _ in range(max(0, row.link_qty)):
            ws.append(line)

    # Column widths computed from the unique (un-expanded) rows for speed.
    widths = [len(c) for c in columns]
    for row in rows:
        for i, value in enumerate(_line(row, sprint, seo, url_type, include_language, language)):
            widths[i] = max(widths[i], len(str(value)))
    for i, width in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = min(width + 4, 70)
    ws.freeze_panes = "A2"


def build_workbook(sheets: dict[str, list[GeneratedRow]], *, sprint: str = "",
                   seo_specialist: str = "", language: str = "",
                   include_language: bool | None = None) -> bytes:
    """Build one .xlsx file. ``sheets`` maps sheet name -> rows.

    Each link becomes its own row. ``Article Language`` is appended as a column
    when a language is set (unless ``include_language`` overrides).
    """
    if include_language is None:
        include_language = bool((language or "").strip())
    columns = BASE_COLUMNS + ([LANG_COLUMN] if include_language else [])

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=_safe_sheet_name(name))
        url_type = "Inner Page" if name == INTERNAL_SHEET else "Main Page"
        _write_sheet(ws, rows, columns, sprint, seo_specialist, url_type, include_language, language)
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
    """Bundle ``filename -> bytes`` into a ZIP archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    return buffer.getvalue()
