"""Smart anchor filter: manage the stop-phrase list used to exclude keywords."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import anchortypes, appsettings
from ..database import get_db
from ..logging_util import log_event
from ..models import IgnoreAnchor
from ..templating import templates

router = APIRouter()


@router.get("/anchor-types", response_class=HTMLResponse)
def anchor_types_page(request: Request):
    """Reference guide: the company's 7-type anchor classification."""
    return templates.TemplateResponse(
        "anchor_types.html",
        {"request": request, "reference": anchortypes.REFERENCE, "active": "anchor-types"},
    )


@router.get("/anchors", response_class=HTMLResponse)
def anchors_page(request: Request, db: Session = Depends(get_db), msg: str = ""):
    phrases = db.query(IgnoreAnchor).order_by(IgnoreAnchor.phrase).all()
    return templates.TemplateResponse(
        "anchors.html",
        {
            "request": request,
            "phrases": phrases,
            "smart_semantic": bool(appsettings.get_slots(db)),
            "active": "anchors",
            "msg": msg,
        },
    )


@router.post("/anchors/add")
async def add_anchors(request: Request, db: Session = Depends(get_db)):
    """Add one or many phrases (one per line)."""
    form = await request.form()
    raw = form.get("phrases") or ""
    existing = {a.phrase.lower() for a in db.query(IgnoreAnchor).all()}
    added = 0
    for line in raw.replace(",", "\n").splitlines():
        phrase = line.strip().lower()
        if phrase and phrase not in existing:
            db.add(IgnoreAnchor(phrase=phrase))
            existing.add(phrase)
            added += 1
    db.commit()
    log_event(db, "INFO", "filter", f"Добавлено стоп-анкоров: {added}")
    return RedirectResponse(f"/anchors?msg=Добавлено: {added}", status_code=303)


@router.post("/anchors/{aid}/delete")
def delete_anchor(aid: int, db: Session = Depends(get_db)):
    a = db.get(IgnoreAnchor, aid)
    if a:
        db.delete(a)
        db.commit()
    return RedirectResponse("/anchors", status_code=303)
