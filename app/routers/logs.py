"""Logs + system settings (OpenRouter keys) + joke API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import appsettings
from ..database import get_db
from ..jokes import get_joke, ping
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
            "key_status": appsettings.slot_status(db),
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


@router.post("/settings/openrouter-key")
def save_openrouter_key(db: Session = Depends(get_db), slot: int = Form(...), key: str = Form("")):
    if slot not in (1, 2):
        raise HTTPException(400, "Неверный слот")
    appsettings.set_setting(db, f"or_key_{slot}", (key or "").strip())
    masked = (key[:8] + "…") if len(key) > 8 else "—"
    log_event(db, "INFO", "settings", f"OpenRouter ключ {slot} {'сохранён' if key.strip() else 'очищен'}", masked)
    return JSONResponse({"ok": True, "slot": slot, "saved": bool((key or '').strip())})


@router.post("/settings/openrouter-check")
def check_openrouter_keys(db: Session = Depends(get_db)):
    result = {}
    for slot, model in appsettings.SLOT_MODELS.items():
        key = appsettings.get_setting(db, f"or_key_{slot}", "").strip()
        result[slot] = "empty" if not key else ("active" if ping(key, model) else "inactive")
    log_event(db, "INFO", "settings", "Проверка ключей OpenRouter",
              ", ".join(f"ключ {s}: {v}" for s, v in result.items()))
    return JSONResponse({"result": result, "models": appsettings.SLOT_MODELS})
