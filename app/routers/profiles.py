"""Anchorless profiles: list + create/edit/delete."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..logging_util import log_event
from ..models import AnchorlessProfile, Strategy
from ..service import profile_example, profile_segments
from ..templating import templates

router = APIRouter()


@router.get("/profiles", response_class=HTMLResponse)
def profiles_page(request: Request, db: Session = Depends(get_db), error: str = "", msg: str = ""):
    parsed = [{
        "obj": p,
        "formats": json.loads(p.items_json or "[]"),
        "example": profile_example(p),
        "segments": profile_segments(p),
    } for p in db.query(AnchorlessProfile).order_by(AnchorlessProfile.id).all()]
    return templates.TemplateResponse(
        "profiles.html",
        {"request": request, "profiles": parsed, "active": "profiles", "error": error, "msg": msg},
    )


@router.post("/profiles/save")
async def save_profile(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    pid = form.get("id")
    name = (form.get("name") or "").strip()
    items = []
    for nm, tpl, pc in zip(form.getlist("item_name"), form.getlist("item_template"), form.getlist("item_percent")):
        tpl = (tpl or "").strip()
        if not tpl:
            continue
        try:
            percent = float(str(pc).replace(",", "."))
        except ValueError:
            percent = 0.0
        items.append({"name": (nm or "").strip(), "template": tpl, "percent": percent})

    if not name:
        return RedirectResponse("/profiles?error=Укажите название профиля", status_code=303)
    if not items:
        return RedirectResponse("/profiles?error=Добавьте хотя бы один формат", status_code=303)

    items_json = json.dumps(items, ensure_ascii=False)
    if pid:
        profile = db.get(AnchorlessProfile, int(pid))
        if not profile:
            raise HTTPException(404, "Профиль не найден")
        profile.name, profile.items_json = name, items_json
    else:
        db.add(AnchorlessProfile(name=name, items_json=items_json))
    db.commit()
    log_event(db, "INFO", "anchorless", f"Сохранён безанкорный профиль «{name}»", f"Форматов: {len(items)}")
    return RedirectResponse("/profiles?msg=Профиль сохранён", status_code=303)


@router.post("/profiles/{pid}/delete")
def delete_profile(pid: int, db: Session = Depends(get_db)):
    profile = db.get(AnchorlessProfile, pid)
    if profile:
        for s in db.query(Strategy).filter(Strategy.anchorless_profile_id == pid).all():
            s.anchorless_profile_id = None
        db.delete(profile)
        db.commit()
    return RedirectResponse("/profiles", status_code=303)
