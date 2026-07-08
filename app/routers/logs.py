"""Logs page + joke API. OpenRouter keys/models now live in Projects → Настройки."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import appsettings
from ..database import get_db
from ..jokes import get_joke
from ..logging_util import log_event
from ..models import Log
from ..templating import templates

router = APIRouter()


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, db: Session = Depends(get_db), level: str = "", category: str = "", msg: str = ""):
    query = db.query(Log)
    if level:
        query = query.filter(Log.level == level)
    if category:
        query = query.filter(Log.category == category)
    logs = query.order_by(Log.created_at.desc(), Log.id.desc()).limit(500).all()
    categories = [c[0] for c in db.query(Log.category).distinct().all()]
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "logs": logs,
            "categories": sorted(categories),
            "levels": ["INFO", "WARNING", "ERROR"],
            "sel_level": level,
            "sel_category": category,
            "active": "logs",
            "msg": msg,
        },
    )


@router.post("/logs/clear")
def clear_logs(db: Session = Depends(get_db)):
    db.query(Log).delete()
    db.commit()
    log_event(db, "WARNING", "logs", "Логи очищены")
    return RedirectResponse("/logs?msg=Логи очищены", status_code=303)


@router.get("/api/joke")
def api_joke(db: Session = Depends(get_db)):
    return {"joke": get_joke(appsettings.get_slots(db))}
