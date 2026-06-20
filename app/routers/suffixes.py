"""Internal pages: per-project paths + the shared suffix dictionary."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..logging_util import log_event
from ..models import SUFFIX_LANGUAGES, InternalPageSuffix, Project
from ..templating import templates

router = APIRouter()


@router.get("/suffixes", response_class=HTMLResponse)
def suffixes_page(request: Request, db: Session = Depends(get_db), msg: str = "", project: str = ""):
    entries = db.query(InternalPageSuffix).order_by(InternalPageSuffix.page_type, InternalPageSuffix.language).all()
    grid: dict[str, dict[str, str]] = {}
    for e in entries:
        grid.setdefault(e.page_type, {})[e.language] = e.suffix
    selected = db.get(Project, int(project)) if project else None
    return templates.TemplateResponse(
        "suffixes.html",
        {
            "request": request,
            "grid": grid,
            "languages": SUFFIX_LANGUAGES,
            "projects": db.query(Project).order_by(Project.id).all(),
            "selected": selected,
            "selected_internal": json.loads(selected.internal_pages_json or "{}") if selected else {},
            "page_types": sorted(grid.keys()),
            "active": "suffixes",
            "msg": msg,
        },
    )


@router.post("/suffixes/save")
async def save_suffix(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    page_type = (form.get("page_type") or "").strip().lower()
    if not page_type:
        return RedirectResponse("/suffixes", status_code=303)
    for lang in SUFFIX_LANGUAGES:
        value = (form.get(f"suffix_{lang}") or "").strip()
        entry = db.query(InternalPageSuffix).filter_by(page_type=page_type, language=lang).first()
        if value:
            if entry:
                entry.suffix = value
            else:
                db.add(InternalPageSuffix(page_type=page_type, language=lang, suffix=value))
        elif entry:
            db.delete(entry)
    db.commit()
    log_event(db, "INFO", "suffix", f"Обновлён справочник суффиксов: «{page_type}»")
    return RedirectResponse("/suffixes?msg=Справочник обновлён", status_code=303)


@router.post("/suffixes/{page_type}/delete")
def delete_suffix(page_type: str, db: Session = Depends(get_db)):
    for e in db.query(InternalPageSuffix).filter_by(page_type=page_type).all():
        db.delete(e)
    db.commit()
    return RedirectResponse("/suffixes", status_code=303)
