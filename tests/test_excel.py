"""Tests for the Excel export (columns, expansion, grouping, language, url type)."""
import io

from openpyxl import load_workbook

from app.excel_export import BASE_COLUMNS, build_workbook
from app.generator import GeneratedRow


def _rows():
    return {
        "Прогоны": [
            GeneratedRow(link_qty=3, url="https://betalice.com/", anchor="https://betalice.com/",
                         article_language="German", keyword=""),
            GeneratedRow(link_qty=2, url="https://betalice.com/", anchor="betalice",
                         article_language="German", keyword=""),
        ],
        "Внутренние страницы": [
            GeneratedRow(link_qty=1, url="https://betalice.com/boni/", anchor="betalice auszahlung",
                         article_language="German", keyword=""),
        ],
    }


def _load(content):
    return load_workbook(io.BytesIO(content))


def test_expanded_columns_and_row_count():
    wb = _load(build_workbook(_rows(), sprint="122", seo_specialist="Miles Nashwood", language="German"))
    ws = wb["Прогоны"]
    header = [c.value for c in ws[1]]
    assert header == BASE_COLUMNS + ["Article Language"]
    # 3 + 2 links expanded -> 5 data rows
    assert ws.max_row - 1 == 5
    first = [c.value for c in ws[2]]
    assert first[0] == "122"                       # Sprint
    assert first[1] == "Miles Nashwood"            # SEO Specialist
    assert first[2] == "betalice.com"              # Project = bare domain
    assert first[3] == "https://betalice.com/"     # Project Url
    assert first[4] == "Main Page"                 # URL Type
    assert first[-1] == "German"                   # Article Language


def test_grouped_has_link_qty_column():
    wb = _load(build_workbook(_rows(), grouped=True, language="German"))
    ws = wb["Прогоны"]
    header = [c.value for c in ws[1]]
    assert header[0] == "Link Q-ty"
    # grouped: one row per anchor -> 2 rows
    assert ws.max_row - 1 == 2
    assert [c.value for c in ws[2]][0] == 3        # quantity in first column


def test_language_omitted_when_empty():
    wb = _load(build_workbook(_rows(), language=""))
    header = [c.value for c in wb["Прогоны"][1]]
    assert "Article Language" not in header


def test_internal_sheet_url_type_inner_page():
    wb = _load(build_workbook(_rows(), language="German"))
    ws = wb["Внутренние страницы"]
    row = [c.value for c in ws[2]]
    assert row[4] == "Inner Page"
    assert row[3] == "https://betalice.com/boni/"
