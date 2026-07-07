"""Date-distribution tab: upload an exported plan, spread it over a date range,
re-export with a Date column. Optional NN anchor classification (separate key)."""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from .. import appsettings, scheduling
from ..database import get_db
from ..jokes import check_key
from ..logging_util import log_event
from ..templating import templates

router = APIRouter()

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, db: Session = Depends(get_db), msg: str = "", error: str = ""):
    key = appsettings.get_setting(db, "or_key_schedule", "").strip()
    masked = ("…" + key[-4:]) if len(key) >= 4 else ("задан" if key else "")
    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "active": "schedule",
            "today": datetime.date.today().isoformat(),
            "key_saved": bool(key),
            "key_masked": masked,
            "key_model": appsettings.get_schedule_model(db),
            "has_any_key": appsettings.get_schedule_slot(db) is not None,
            "msg": msg,
            "error": error,
        },
    )


@router.post("/schedule/generate")
async def schedule_generate(request: Request, db: Session = Depends(get_db),
                            file: UploadFile = None, days: int = Form(30),
                            start_date: str = Form(""), use_model: str = Form("")):
    if file is None or not getattr(file, "filename", ""):
        return RedirectResponse("/schedule?error=Выберите файл плана (Excel).", status_code=303)
    if days < 1:
        return RedirectResponse("/schedule?error=Количество дней должно быть ≥ 1.", status_code=303)
    try:
        start = datetime.date.fromisoformat(start_date) if start_date else datetime.date.today()
    except ValueError:
        return RedirectResponse("/schedule?error=Неверная дата начала.", status_code=303)

    content = await file.read()
    try:
        header, links = scheduling.read_plan(content)
    except Exception:
        return RedirectResponse("/schedule?error=Не удалось прочитать файл. Нужен Excel, выгруженный из проектов.",
                                status_code=303)
    if not links:
        return RedirectResponse("/schedule?error=В файле нет строк со ссылками.", status_code=303)

    # Optional NN refinement of anchor categories (separate key).
    mode = "по типам анкоров"
    if use_model == "on":
        slot = appsettings.get_schedule_slot(db)
        if slot:
            distinct = sorted({l["anchor"] for l in links})
            labels = scheduling.classify_with_model(distinct, slot[0], slot[1])
            if labels:
                for l in links:
                    l["category"] = labels.get(l["anchor"], l["category"])
                mode = f"нейросеть ({slot[1]})"

    placements = scheduling.distribute(links, days, start)
    summary = scheduling.summarize(links, days)
    content_out = scheduling.build_scheduled_workbook(header, placements)

    end = start + datetime.timedelta(days=days - 1)
    log_event(db, "INFO", "schedule", f"Распределение по датам: {summary['total']} ссылок на {days} дн.",
              f"{start.isoformat()}—{end.isoformat()}, ~{summary['per_day']}/день; "
              f"безанкор {summary['anchorless']}, бренд {summary['branded']}, "
              f"коммерч {summary['commercial']}; классификация: {mode}")
    fname = f"planning-{start.isoformat()}-{days}d.xlsx"
    return Response(content=content_out, media_type=XLSX_MEDIA,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/schedule/key")
def save_schedule_key(db: Session = Depends(get_db), key: str = Form(""),
                      model: str = Form(""), action: str = Form("save")):
    appsettings.set_setting(db, "or_model_schedule", (model or "").strip())
    if action == "clear":
        appsettings.set_setting(db, "or_key_schedule", "")
        log_event(db, "INFO", "settings", "Ключ распределения по датам очищен")
        return RedirectResponse("/schedule?msg=Ключ очищен", status_code=303)
    value = (key or "").strip()
    if value:
        appsettings.set_setting(db, "or_key_schedule", value)
        log_event(db, "INFO", "settings", "Ключ распределения по датам сохранён", f"{value[:8]}…")
        return RedirectResponse("/schedule?msg=Ключ сохранён", status_code=303)
    return RedirectResponse("/schedule?msg=Модель сохранена", status_code=303)


@router.post("/schedule/check")
def check_schedule_key(db: Session = Depends(get_db)):
    slot = appsettings.get_schedule_slot(db)
    if not slot:
        return RedirectResponse("/schedule?msg=Ключ не задан (можно и без него — тогда по типам анкоров).",
                                status_code=303)
    ok, detail = check_key(slot[0])
    return RedirectResponse(f"/schedule?msg=Проверка ключа: {'✓ ' + detail if ok else '✗ ' + detail}",
                            status_code=303)
