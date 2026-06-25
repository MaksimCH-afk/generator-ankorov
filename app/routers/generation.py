"""Generation: the screen, the async generate→token→download flow, preview,
lazy per-project breakdown, and the optional smart anchor filter."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from .. import anchor_filter, appsettings
from ..database import get_db
from ..excel_export import build_workbook, build_zip, safe_filename
from ..helpers import project_progress, record_history
from ..logging_util import log_event
from ..models import ARTICLE_LANGUAGES, SEO_SPECIALISTS, IgnoreAnchor, Project, Strategy
from ..service import generate_project_sheets, project_breakdown, strategy_label, strategy_segments
from ..templating import templates

router = APIRouter()

# Short-lived store for generated files awaiting download (modal flow).
_GENERATED: dict[str, dict] = {}


@router.get("/generate", response_class=HTMLResponse)
def generate_page(request: Request, db: Session = Depends(get_db), msg: str = "", error: str = ""):
    projects = db.query(Project).order_by(Project.id).all()
    strategies = db.query(Strategy).order_by(Strategy.id).all()
    gen_views = [
        {"obj": p, "ready": project_progress(p)["ready"],
         "segments": strategy_segments(p.strategy) if p.strategy else []}
        for p in projects
    ]
    ignore_count = db.query(IgnoreAnchor).count()
    return templates.TemplateResponse(
        "generate.html",
        {
            "request": request,
            "gen_views": gen_views,
            "strategy_options": [{"id": s.id, "label": strategy_label(s)} for s in strategies],
            "article_languages": ARTICLE_LANGUAGES,
            "seo_specialists": SEO_SPECIALISTS,
            "ignore_count": ignore_count,
            "smart_semantic": bool(appsettings.get_slots(db)),
            "active": "generate",
            "msg": msg,
            "error": error,
        },
    )


@router.get("/projects/{pid}/breakdown")
def project_breakdown_api(pid: int, db: Session = Depends(get_db)):
    """Lazy per-project anchor breakdown (loaded on demand on the Generate page)."""
    project = db.get(Project, pid)
    if not project:
        return JSONResponse({"rows": []})
    return JSONResponse({"rows": project_breakdown(db, project)})


@router.get("/projects/{pid}/preview", response_class=HTMLResponse)
def preview(pid: int, request: Request, db: Session = Depends(get_db)):
    project = db.get(Project, pid)
    if not project:
        from fastapi import HTTPException
        raise HTTPException(404, "Проект не найден")
    sheets = generate_project_sheets(db, project)
    totals = {name: sum(r.link_qty for r in rows) for name, rows in sheets.items()}
    return templates.TemplateResponse(
        "preview.html",
        {
            "request": request,
            "project": project,
            "sheets": sheets,
            "totals": totals,
            "include_language": bool((project.language or "").strip()),
            "active": "generate",
        },
    )


@router.post("/generate")
async def generate(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    pids = [int(x) for x in form.getlist("project_ids")]
    export_format = form.get("export_format", "separate")
    sprint = (form.get("sprint") or "").strip()
    seo_specialist = (form.get("seo_specialist") or "").strip()
    grouped = form.get("group_mode") == "group"
    smart = form.get("smart_filter") == "on"
    if not pids:
        return JSONResponse({"error": "Выберите хотя бы один проект."}, status_code=400)

    phrases = [a.phrase for a in db.query(IgnoreAnchor).all()] if smart else []
    slots = appsettings.get_slots(db) if smart else []

    projects = db.query(Project).filter(Project.id.in_(pids)).all()
    files: dict[str, bytes] = {}
    results = []
    for project in projects:
        exclude: set[str] = set()
        if smart and phrases:
            kept, removed, mode = anchor_filter.filter_keywords(
                [k.keyword for k in project.keywords], phrases, slots)
            exclude = removed
            if removed:
                log_event(db, "INFO", "filter",
                          f"Умный фильтр анкоров: {project.url} — исключено {len(removed)} ключей ({mode})",
                          ", ".join(sorted(removed))[:500])
        sheets = generate_project_sheets(db, project, exclude_keywords=exclude)
        if not sheets:
            continue
        files[safe_filename(project.url)] = build_workbook(
            sheets, sprint=sprint, seo_specialist=seo_specialist,
            language=project.language or "", brand=project.brand or "", grouped=grouped)
        links = sum(r.link_qty for rows in sheets.values() for r in rows)
        results.append({"file": safe_filename(project.url), "links": links, "lang": project.language or "—"})
        record_history(db, project, export_format, sheets)
        log_event(db, "INFO", "generate", f"Сгенерирован {project.url}",
                  f"Стратегия: {project.strategy.name if project.strategy else '—'}, "
                  f"формат: {export_format}, строки: {'группировка' if grouped else 'развёрнуто'}"
                  f"{', умный фильтр' if smart else ''}")
    db.commit()

    if not files:
        log_event(db, "WARNING", "generate", "Генерация без результата",
                  "У выбранных проектов нет данных: задайте стратегию, объём и частотку.")
        return JSONResponse({"error": "Нет данных для генерации. Проверьте стратегию, объём и частотку."},
                            status_code=400)

    token = uuid.uuid4().hex
    if len(files) == 1 and export_format != "zip":
        filename, content = next(iter(files.items()))
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        filename, content, media = "anchor-plans.zip", build_zip(files), "application/zip"
    _GENERATED[token] = {"filename": filename, "content": content, "media": media}
    if len(_GENERATED) > 20:
        for k in list(_GENERATED)[:-20]:
            _GENERATED.pop(k, None)

    return JSONResponse({
        "token": token,
        "count": len(results),
        "total": sum(r["links"] for r in results),
        "results": results,
        "download_label": "ZIP-архив" if filename.endswith(".zip") else "файл",
        "sprint": sprint,
    })


@router.get("/generate/download/{token}")
def download_generated(token: str):
    data = _GENERATED.pop(token, None)
    if not data:
        return RedirectResponse("/generate?error=Файл устарел, сгенерируйте заново.", status_code=303)
    return Response(
        content=data["content"], media_type=data["media"],
        headers={"Content-Disposition": f'attachment; filename="{data["filename"]}"'},
    )
