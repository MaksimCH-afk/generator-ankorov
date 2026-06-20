"""Generation history."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..logging_util import log_event
from ..models import History
from ..templating import templates

router = APIRouter()


@router.get("/history", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db), msg: str = ""):
    records = db.query(History).order_by(History.created_at.desc(), History.id.desc()).limit(500).all()
    parsed = [{"obj": r, "sheets": json.loads(r.sheets_json or "{}")} for r in records]
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "records": parsed, "active": "history", "msg": msg},
    )


@router.post("/history/clear")
def clear_history(db: Session = Depends(get_db)):
    db.query(History).delete()
    db.commit()
    log_event(db, "WARNING", "history", "История очищена")
    return RedirectResponse("/history?msg=История очищена", status_code=303)
