"""Date-distribution tab: upload an exported plan, spread it over a date range,
re-export with a Date column. Optional NN anchor classification (separate key)."""
from __future__ import annotations

import datetime
import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from .. import appsettings, scheduling
from ..database import get_db
from ..excel_export import build_zip
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
            "key_model_cheap": appsettings.get_schedule_cheap_model(db),
            "has_any_key": appsettings.get_schedule_slot(db) is not None,
            "msg": msg,
            "error": error,
        },
    )


@router.post("/schedule/generate")
async def schedule_generate(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    uploads = [f for f in form.getlist("files") if getattr(f, "filename", "")]
    if not uploads:
        return RedirectResponse("/schedule?error=Выберите файл(ы) плана (Excel).", status_code=303)
    try:
        days = int(form.get("days") or 30)
    except ValueError:
        days = 0
    if days < 1:
        return RedirectResponse("/schedule?error=Количество дней должно быть ≥ 1.", status_code=303)
    try:
        sd = (form.get("start_date") or "").strip()
        start = datetime.date.fromisoformat(sd) if sd else datetime.date.today()
    except ValueError:
        return RedirectResponse("/schedule?error=Неверная дата начала.", status_code=303)
    use_model = form.get("use_model") == "on"

    # Parse every uploaded plan.
    plans = []  # (out_name, header, links)
    for up in uploads:
        try:
            header, links = scheduling.read_plan(await up.read())
        except Exception:
            continue
        if links:
            base = os.path.splitext(os.path.basename(up.filename))[0]
            plans.append((base, header, links))
    if not plans:
        return RedirectResponse("/schedule?error=В файлах нет строк со ссылками (нужен Excel из проектов).",
                                status_code=303)

    # Classify DISTINCT anchors across ALL files once (smart model for the few
    # uniques, cheap model as fallback), then apply the buckets to every link.
    mode = "по типам анкоров"
    if use_model:
        smart = appsettings.get_schedule_slot(db)
        cheap = appsettings.get_schedule_cheap_slot(db)
        if smart:
            all_anchors = {l["anchor"] for _, _, links in plans for l in links}
            buckets = scheduling.classify_buckets(all_anchors, smart_slot=smart, cheap_slot=cheap)
            for _, _, links in plans:
                for l in links:
                    if l["anchor"] in buckets:
                        l["category"] = buckets[l["anchor"]]
            mode = f"нейросеть ({smart[1]}" + (f" + {cheap[1]}" if cheap else "") + ")"

    # Distribute each file independently over the same window.
    files: dict[str, bytes] = {}
    total_links = 0
    for base, header, links in plans:
        placements = scheduling.distribute(links, days, start)
        files[f"{base}-{start.isoformat()}-{days}d.xlsx"] = scheduling.build_scheduled_workbook(header, placements)
        total_links += len(links)

    end = start + datetime.timedelta(days=days - 1)
    log_event(db, "INFO", "schedule",
              f"Распределение по датам: {len(plans)} файл(ов), {total_links} ссылок на {days} дн.",
              f"{start.isoformat()}—{end.isoformat()}; классификация: {mode}")

    if len(files) == 1:
        name, content_out = next(iter(files.items()))
        return Response(content=content_out, media_type=XLSX_MEDIA,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    zip_name = f"planning-{start.isoformat()}-{days}d.zip"
    return Response(content=build_zip(files), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{zip_name}"'})


@router.post("/schedule/key")
def save_schedule_key(db: Session = Depends(get_db), key: str = Form(""),
                      model: str = Form(""), model_cheap: str = Form(""), action: str = Form("save")):
    appsettings.set_setting(db, "or_model_schedule", (model or "").strip())
    appsettings.set_setting(db, "or_model_schedule_cheap", (model_cheap or "").strip())
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
