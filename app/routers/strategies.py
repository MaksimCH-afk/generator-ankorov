"""Strategies (anchor profiles): list + create/edit/delete."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import generator as gen
from ..database import get_db
from ..logging_util import log_event
from ..models import AnchorlessProfile, Project, Strategy
from ..service import anchorless_summary, strategy_segments
from ..templating import templates

router = APIRouter()


def _parse_roles(names: list[str], percents: list[str]) -> list[gen.Role]:
    roles = []
    for name, percent in zip(names, percents):
        name = name.strip()
        if not name:
            continue
        try:
            roles.append(gen.Role(name=name, percent=float(str(percent).replace(",", "."))))
        except ValueError:
            continue
    return roles


@router.get("/strategies", response_class=HTMLResponse)
def strategies_page(request: Request, db: Session = Depends(get_db), error: str = "", msg: str = ""):
    parsed = [{
        "obj": s,
        "roles": json.loads(s.roles_json),
        "anchorless": anchorless_summary(s),
        "profile_name": s.anchorless_profile.name if s.anchorless_profile else "100% голый URL",
        "segments": strategy_segments(s),
    } for s in db.query(Strategy).order_by(Strategy.id).all()]
    return templates.TemplateResponse(
        "strategies.html",
        {
            "request": request,
            "strategies": parsed,
            "anchorless_profiles": db.query(AnchorlessProfile).order_by(AnchorlessProfile.id).all(),
            "active": "strategies",
            "error": error,
            "msg": msg,
        },
    )


@router.post("/strategies/save")
async def save_strategy(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    sid = form.get("id")
    name = (form.get("name") or "").strip()
    try:
        anchorless = float(str(form.get("anchorless_percent", "0")).replace(",", "."))
    except ValueError:
        anchorless = 0.0
    roles = _parse_roles(form.getlist("role_name"), form.getlist("role_percent"))

    if not name:
        return RedirectResponse("/strategies?error=Укажите название стратегии", status_code=303)
    err = gen.validate_strategy_sum(anchorless, roles)
    if err:
        return RedirectResponse(f"/strategies?error={err}", status_code=303)

    roles_json = json.dumps([{"name": r.name, "percent": r.percent} for r in roles], ensure_ascii=False)
    apid = form.get("anchorless_profile_id")
    profile_id = int(apid) if apid else None
    if sid:
        strategy = db.get(Strategy, int(sid))
        if not strategy:
            raise HTTPException(404, "Стратегия не найдена")
        strategy.name, strategy.anchorless_percent = name, anchorless
        strategy.roles_json, strategy.anchorless_profile_id = roles_json, profile_id
        action = "обновлена"
    else:
        db.add(Strategy(name=name, anchorless_percent=anchorless, roles_json=roles_json,
                        anchorless_profile_id=profile_id))
        action = "создана"
    db.commit()
    log_event(db, "INFO", "strategy", f"Стратегия «{name}» {action}", f"Безанкор {anchorless}%, ролей: {len(roles)}")
    return RedirectResponse("/strategies?msg=Стратегия сохранена", status_code=303)


@router.post("/strategies/{sid}/delete")
def delete_strategy(sid: int, db: Session = Depends(get_db)):
    strategy = db.get(Strategy, sid)
    if strategy:
        for p in db.query(Project).filter(Project.strategy_id == sid).all():
            p.strategy_id = None
        db.delete(strategy)
        db.commit()
    return RedirectResponse("/strategies", status_code=303)
