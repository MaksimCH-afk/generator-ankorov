"""Logs + system settings (OpenRouter keys) + joke API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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

    def masked(slot: int) -> str:
        k = appsettings.get_setting(db, f"or_key_{slot}", "").strip()
        return ("…" + k[-4:]) if len(k) >= 4 else ("задан" if k else "")

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
            "key_masked": {1: masked(1), 2: masked(2)},
            "key_models": appsettings.SLOT_MODELS,
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
def save_openrouter_key(db: Session = Depends(get_db), slot: int = Form(...),
                        key: str = Form(""), action: str = Form("save")):
    if slot not in (1, 2):
        raise HTTPException(400, "Неверный слот")
    if action == "clear":
        appsettings.set_setting(db, f"or_key_{slot}", "")
        log_event(db, "INFO", "settings", f"OpenRouter ключ {slot} очищен")
        return RedirectResponse(f"/logs?msg=Ключ {slot} очищен", status_code=303)
    value = (key or "").strip()
    if not value:
        return RedirectResponse(f"/logs?msg=Введите ключ для слота {slot}", status_code=303)
    appsettings.set_setting(db, f"or_key_{slot}", value)
    log_event(db, "INFO", "settings", f"OpenRouter ключ {slot} сохранён", value[:8] + "…")
    return RedirectResponse(f"/logs?msg=Ключ {slot} сохранён. Нажмите «Проверить ключи».", status_code=303)


@router.post("/settings/openrouter-check")
def check_openrouter_keys(db: Session = Depends(get_db)):
    label = {"active": "активен", "inactive": "не отвечает", "empty": "пусто"}
    parts = []
    for slot, model in appsettings.SLOT_MODELS.items():
        key = appsettings.get_setting(db, f"or_key_{slot}", "").strip()
        state = "empty" if not key else ("active" if ping(key, model) else "inactive")
        parts.append(f"слот {slot}: {label[state]}")
    log_event(db, "INFO", "settings", "Проверка ключей OpenRouter", ", ".join(parts))
    return RedirectResponse(f"/logs?msg=Проверка — {', '.join(parts)}", status_code=303)
