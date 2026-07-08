"""Date-distribution tab: upload an exported plan, spread it over a date range,
re-export with a Date column. Optional NN anchor classification (separate key)."""
from __future__ import annotations

import datetime
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from .. import appsettings, scheduling
from ..database import get_db
from ..excel_export import build_zip
from ..logging_util import log_event
from ..models import ScheduleRun
from ..templating import templates

router = APIRouter()

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_HISTORY_LIMIT = 50


@router.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, db: Session = Depends(get_db), msg: str = "", error: str = ""):
    history = db.query(ScheduleRun).order_by(ScheduleRun.created_at.desc(), ScheduleRun.id.desc()).limit(50).all()
    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "active": "schedule",
            "today": datetime.date.today().isoformat(),
            "key_model": appsettings.get_schedule_model(db),
            "key_model_cheap": appsettings.get_schedule_cheap_model(db),
            "has_any_key": appsettings.has_key(db),
            "history": history,
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
        out_name, out_content = next(iter(files.items()))
        out_media = XLSX_MEDIA
    else:
        out_name = f"planning-{start.isoformat()}-{len(files)}files.zip"
        out_content, out_media = build_zip(files), "application/zip"

    # Save to history so the result can be re-downloaded any time.
    summary = (f"{len(plans)} файл(ов), {total_links} ссылок"
               + (" · индивидуальные сроки" if per_file else f" · {days} дн. с {start.isoformat()}")
               + f" · {mode}")
    db.add(ScheduleRun(filename=out_name, media_type=out_media, summary=summary, content=out_content))
    db.commit()
    _prune_history(db)

    return Response(content=out_content, media_type=out_media,
                    headers={"Content-Disposition": f'attachment; filename="{out_name}"'})


def _prune_history(db: Session) -> None:
    """Keep only the most recent runs to bound DB growth."""
    old = (db.query(ScheduleRun).order_by(ScheduleRun.created_at.desc(), ScheduleRun.id.desc())
           .offset(_HISTORY_LIMIT).all())
    for row in old:
        db.delete(row)
    if old:
        db.commit()


@router.get("/schedule/history/{run_id}")
def download_history(run_id: int, db: Session = Depends(get_db)):
    run = db.get(ScheduleRun, run_id)
    if not run:
        raise HTTPException(404, "Результат не найден")
    return Response(content=run.content, media_type=run.media_type,
                    headers={"Content-Disposition": f'attachment; filename="{run.filename}"'})


@router.post("/schedule/history/{run_id}/delete")
def delete_history(run_id: int, db: Session = Depends(get_db)):
    run = db.get(ScheduleRun, run_id)
    if run:
        db.delete(run)
        db.commit()
    return RedirectResponse("/schedule?msg=Запись истории удалена", status_code=303)


@router.post("/schedule/history/clear")
def clear_history(db: Session = Depends(get_db)):
    db.query(ScheduleRun).delete()
    db.commit()
    return RedirectResponse("/schedule?msg=История распределений очищена", status_code=303)
