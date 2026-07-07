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
    # Per-file periods/start dates (aligned to upload order); global values are
    # the fallback for any file without its own values.
    per_file = form.get("per_file") == "on"
    per_days = form.getlist("per_days")
    per_start = form.getlist("per_start")

    def resolve_days(i: int) -> int:
        if per_file and i < len(per_days):
            try:
                v = int(per_days[i])
                if v >= 1:
                    return v
            except ValueError:
                pass
        return days

    def resolve_start(i: int) -> datetime.date:
        if per_file and i < len(per_start) and str(per_start[i]).strip():
            try:
                return datetime.date.fromisoformat(str(per_start[i]).strip())
            except ValueError:
                pass
        return start

    # Parse every uploaded plan (keep its own days/start by upload index).
    plans = []  # (base, header, links, days_i, start_i)
    for i, up in enumerate(uploads):
        try:
            header, links = scheduling.read_plan(await up.read())
        except Exception:
            continue
        if links:
            base = os.path.splitext(os.path.basename(up.filename))[0]
            plans.append((base, header, links, resolve_days(i), resolve_start(i)))
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
            all_anchors = {l["anchor"] for _, _, links, _, _ in plans for l in links}
            buckets = scheduling.classify_buckets(all_anchors, smart_slot=smart, cheap_slot=cheap)
            for _, _, links, _, _ in plans:
                for l in links:
                    if l["anchor"] in buckets:
                        l["category"] = buckets[l["anchor"]]
            mode = f"нейросеть ({smart[1]}" + (f" + {cheap[1]}" if cheap else "") + ")"

    # Distribute each file independently over its own window.
    files: dict[str, bytes] = {}
    total_links = 0
    for base, header, links, days_i, start_i in plans:
        placements = scheduling.distribute(links, days_i, start_i)
        files[f"{base}-{start_i.isoformat()}-{days_i}d.xlsx"] = \
            scheduling.build_scheduled_workbook(header, placements)
        total_links += len(links)

    windows = "; ".join(f"{b}: {s.isoformat()} +{d}д" for b, _, _, d, s in plans)
    log_event(db, "INFO", "schedule",
              f"Распределение по датам: {len(plans)} файл(ов), {total_links} ссылок"
              + (" (индивидуальные сроки)" if per_file else f", {days} дн."),
              f"{windows}; классификация: {mode}")

    if len(files) == 1:
        name, content_out = next(iter(files.items()))
        return Response(content=content_out, media_type=XLSX_MEDIA,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    zip_name = f"planning-{start.isoformat()}-{len(files)}files.zip"
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
