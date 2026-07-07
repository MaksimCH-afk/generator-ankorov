"""Date distribution ("Распределение по датам").

Independent feature: takes a previously-exported link plan (Excel), spreads its
links evenly across a date range, and re-exports with a ``Date`` column instead
of ``Sprint``.

Distribution rules (see spec):
* total links / days = average per day; the remainder is **not** dumped on one
  day — the extra links are spread evenly across the period (every ~days/rem-th
  day gets +1).
* anchorless links (bare URL/domain) are the safe bulk and fill most of each
  day; commercial/branded anchors are spread evenly so they recur regularly but
  never cluster (no spammy day). This is achieved by interleaving all links by
  fractional rank within their category, then slicing the sequence into days.

Anchor category is taken from the plan's ``Anchor Type`` column (BD/EM/PM) plus a
bare-URL check, and can optionally be refined by an OpenRouter model (cheap by
design — a mini model is plenty for 3-way classification).
"""
from __future__ import annotations

import datetime
import io
from collections import defaultdict

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import get_column_letter

from . import anchortypes
from .excel_export import HEADER_FILL, HEADER_FONT

# Cadence buckets used by the distribution: anchorless = safe bulk, branded =
# regular, commercial = spread pointwise.
ANCHORLESS, BRANDED, COMMERCIAL = "anchorless", "branded", "commercial"
_PRIORITY = {COMMERCIAL: 0, BRANDED: 1, ANCHORLESS: 2}

# Company 7-type -> cadence bucket.
_BUCKET = {
    anchortypes.ND: ANCHORLESS, anchortypes.NT: ANCHORLESS,
    anchortypes.BD: BRANDED, anchortypes.G: BRANDED,
    anchortypes.EM: COMMERCIAL, anchortypes.PM: COMMERCIAL, anchortypes.BDPM: COMMERCIAL,
}


def bucket_of(type_code: str) -> str:
    return _BUCKET.get((type_code or "").strip().upper(), COMMERCIAL)


def classify(anchor: str, anchor_type: str) -> str:
    """Cadence bucket from the plan's Anchor Type column (any of the 7 codes),
    falling back to the deterministic company classifier on the anchor text."""
    if anchortypes.looks_naked_url(anchor):
        return ANCHORLESS  # a naked URL is always safe filler, regardless of label
    at = (anchor_type or "").strip().upper()
    if at in _BUCKET:
        return bucket_of(at)
    return bucket_of(anchortypes.classify_one(anchor))


def read_plan(content: bytes) -> tuple[list[str], list[dict]]:
    """Parse an exported plan into ``(header, links)``.

    Each link is ``{"row": [values aligned to header], "anchor": str,
    "category": str}``. A ``Link Q-ty`` column (grouped export) is expanded to
    one link per unit. Trailing empty columns are trimmed.
    """
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = [["" if c is None else str(c).strip() for c in r] for r in ws.iter_rows(values_only=True)]
    rows = [r for r in rows if any(r)]
    if not rows:
        return [], []
    header = rows[0][:]
    while header and not header[-1]:
        header.pop()
    ncol = len(header)
    idx = {name: i for i, name in enumerate(header)}
    qty_i = idx.get("Link Q-ty")
    anchor_i = idx.get("Anchor")
    at_i = idx.get("Anchor Type")

    links: list[dict] = []
    for raw in rows[1:]:
        row = [(raw[i] if i < len(raw) else "") for i in range(ncol)]
        anchor = row[anchor_i] if anchor_i is not None else ""
        if not anchor:
            continue
        at = row[at_i] if at_i is not None else ""
        cat = classify(anchor, at)
        n = 1
        if qty_i is not None:
            try:
                n = max(1, int(float(row[qty_i])))
            except (ValueError, TypeError):
                n = 1
        for _ in range(n):
            links.append({"row": row[:], "anchor": anchor, "category": cat})
    return header, links


def day_capacities(total: int, days: int) -> list[int]:
    """How many links each day carries: base = total//days, remainder spread
    evenly (every ~days/rem-th day gets +1). Sums to ``total``."""
    if days <= 0:
        return []
    base, rem = divmod(total, days)
    caps = [base] * days
    for k in range(rem):
        d = min(int((k + 0.5) * days / rem), days - 1)
        caps[d] += 1
    return caps


def order_links(links: list[dict]) -> list[dict]:
    """Interleave links so each category is spread evenly across the sequence
    (fractional-rank merge). Money anchors get placed before filler on ties."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for l in links:
        groups[l["category"]].append(l)
    ranked = []
    for cat, items in groups.items():
        n = len(items)
        for i, it in enumerate(items):
            ranked.append(((i + 0.5) / n, _PRIORITY.get(cat, 3), it))
    ranked.sort(key=lambda x: (x[0], x[1]))
    return [it for _, _, it in ranked]


def distribute(links: list[dict], days: int, start_date: datetime.date) -> list[tuple[datetime.date, dict]]:
    """Assign each link a date. Returns ``[(date, link), ...]`` in calendar order."""
    caps = day_capacities(len(links), days)
    ordered = order_links(links)
    out: list[tuple[datetime.date, dict]] = []
    pos = 0
    for d, cap in enumerate(caps):
        date = start_date + datetime.timedelta(days=d)
        for _ in range(cap):
            if pos >= len(ordered):
                break
            out.append((date, ordered[pos]))
            pos += 1
    return out


def classify_with_model(anchors: list[str], key: str, model: str) -> dict[str, str]:
    """Optional NN refinement (company 7-type rubric) mapped to cadence buckets."""
    types = anchortypes.llm_classify(anchors, key, model)
    return {a: bucket_of(code) for a, code in types.items()}


def build_scheduled_workbook(header: list[str], placements: list[tuple[datetime.date, dict]],
                             date_fmt: str = "%d.%m.%Y") -> bytes:
    """Write the re-scheduled plan: ``Sprint`` column becomes ``Date``."""
    sprint_i = header.index("Sprint") if "Sprint" in header else None
    out_header = ["Date" if h == "Sprint" else h for h in header]
    if sprint_i is None:
        out_header = ["Date"] + out_header  # no Sprint column -> prepend Date

    def make_row(date, link):
        row = link["row"][:]
        if sprint_i is not None:
            row[sprint_i] = date.strftime(date_fmt)
            return row
        return [date.strftime(date_fmt)] + row

    widths = [len(c) for c in out_header]
    for date, link in placements:
        for i, v in enumerate(make_row(date, link)):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(v)))

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title="Планнинг по датам")
    for i, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = min(w + 4, 70)
    ws.freeze_panes = "A2"
    head = []
    for col in out_header:
        cell = WriteOnlyCell(ws, value=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        head.append(cell)
    ws.append(head)
    for date, link in placements:
        ws.append(make_row(date, link))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def summarize(links: list[dict], days: int) -> dict:
    """Quick stats for the UI / logs."""
    cats = defaultdict(int)
    for l in links:
        cats[l["category"]] += 1
    total = len(links)
    return {
        "total": total,
        "per_day": round(total / days, 1) if days else 0,
        "anchorless": cats[ANCHORLESS],
        "branded": cats[BRANDED],
        "commercial": cats[COMMERCIAL],
    }
