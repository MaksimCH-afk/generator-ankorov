"""Projects: dashboard, project settings (by block), import, export, bulk actions."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..excel_export import build_workbook, safe_filename
from ..helpers import match_project, project_progress, project_view, record_history
from ..logging_util import log_event
from ..models import ARTICLE_LANGUAGES, Keyword, Project, Strategy
from ..parsing import normalize_domain, parse_frequency, parse_project_sheets, parse_project_table
from ..service import generate_project_sheets, strategy_label
from ..templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), msg: str = "", error: str = ""):
    projects = db.query(Project).order_by(Project.id).all()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "project_views": [project_view(p) for p in projects],
            "progress": {p.id: project_progress(p) for p in projects},
            "strategies": db.query(Strategy).order_by(Strategy.id).all(),
            "strategy_options": [{"id": s.id, "label": strategy_label(s)} for s in db.query(Strategy).all()],
            "article_languages": ARTICLE_LANGUAGES,
            "active": "dashboard",
            "msg": msg,
            "error": error,
        },
    )


@router.get("/projects/{pid}", response_class=HTMLResponse)
def project_page(pid: int, request: Request, db: Session = Depends(get_db), msg: str = ""):
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    strategies = db.query(Strategy).order_by(Strategy.id).all()
    return templates.TemplateResponse(
        "project.html",
        {
            "request": request,
            "project": project,
            "strategy_options": [{"id": s.id, "label": strategy_label(s)} for s in strategies],
            "article_languages": ARTICLE_LANGUAGES,
            "keywords": project.keywords,
            "progress": project_progress(project),
            "active": "dashboard",
            "msg": msg,
        },
    )


@router.post("/projects/create")
def create_project(db: Session = Depends(get_db), url: str = Form(...),
                   language: str = Form(""), brand: str = Form("")):
    canonical = normalize_domain(url.strip())
    if db.query(Project).filter(Project.url == canonical).first():
        return RedirectResponse(f"/?error=Проект {canonical} уже существует.", status_code=303)
    project = Project(url=canonical, language=language.strip(), brand=brand.strip())
    db.add(project)
    db.commit()
    log_event(db, "INFO", "project", f"Создан проект {project.url}", f"Бренд: {project.brand or '—'}")
    return RedirectResponse(f"/projects/{project.id}?msg=Проект создан", status_code=303)


@router.post("/projects/{pid}/basics")
async def update_basics(pid: int, request: Request, db: Session = Depends(get_db)):
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    form = await request.form()
    project.url = normalize_domain((form.get("url") or project.url).strip())
    project.language = (form.get("language") or "").strip()
    project.brand = (form.get("brand") or "").strip()
    db.commit()
    log_event(db, "INFO", "project", f"Обновлены параметры проекта {project.url}",
              f"Язык: {project.language or '— не указан —'}, бренд: {project.brand or '—'}")
    return RedirectResponse(f"/projects/{pid}?msg=Основные параметры сохранены", status_code=303)


@router.post("/projects/{pid}/volume")
def update_volume(pid: int, db: Session = Depends(get_db), volume: int = Form(0), next: str = Form("")):
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    project.volume = max(0, int(volume or 0))
    db.commit()
    log_event(db, "INFO", "project", f"Объём проекта {project.url} → {project.volume}")
    if next.startswith("/"):
        return RedirectResponse(next, status_code=303)
    return RedirectResponse(f"/projects/{pid}?msg=Объём сохранён", status_code=303)


@router.post("/projects/{pid}/language")
def set_project_language(pid: int, db: Session = Depends(get_db), language: str = Form("")):
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    project.language = (language or "").strip()
    db.commit()
    return RedirectResponse("/generate", status_code=303)


@router.post("/projects/{pid}/strategy")
def set_project_strategy(pid: int, db: Session = Depends(get_db),
                         strategy_id: str = Form(""), next: str = Form("/generate")):
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    project.strategy_id = int(strategy_id) if strategy_id else None
    db.commit()
    name = project.strategy.name if project.strategy else "—"
    log_event(db, "INFO", "project", f"Стратегия проекта {project.url} → {name}")
    return RedirectResponse(next if next.startswith("/") else "/generate", status_code=303)


@router.post("/projects/{pid}/redistribution")
def update_redistribution(pid: int, db: Session = Depends(get_db), redistribution_json: str = Form("")):
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    raw = (redistribution_json or "").strip()
    if raw:
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            return RedirectResponse(f"/projects/{pid}?msg=Ошибка: некорректный JSON перераспределения",
                                    status_code=303)
        project.redistribution_json = raw
    else:
        project.redistribution_json = "{}"
    db.commit()
    return RedirectResponse(f"/projects/{pid}?msg=Перераспределение сохранено", status_code=303)


@router.post("/projects/{pid}/internal")
async def update_internal_pages(pid: int, request: Request, db: Session = Depends(get_db)):
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    form = await request.form()
    project.internal_language = form.get("internal_language") or "en"
    internal: dict[str, str] = {}
    for pt, path in zip(form.getlist("ip_type"), form.getlist("ip_path")):
        pt, path = pt.strip().lower(), path.strip()
        if pt and path:
            internal[pt] = path
    project.internal_pages_json = json.dumps(internal, ensure_ascii=False)
    db.commit()
    log_event(db, "INFO", "suffix", f"Внутренние страницы проекта {project.url} обновлены",
              f"Страниц: {len(internal)}, язык: {project.internal_language}")
    return RedirectResponse(f"/suffixes?project={pid}&msg=Внутренние страницы проекта сохранены", status_code=303)


@router.post("/projects/{pid}/delete")
def delete_project(pid: int, db: Session = Depends(get_db)):
    project = db.get(Project, pid)
    if project:
        url = project.url
        db.delete(project)
        db.commit()
        log_event(db, "WARNING", "project", f"Удалён проект {url}")
    return RedirectResponse("/", status_code=303)


@router.post("/projects/delete-all")
def delete_all_projects(db: Session = Depends(get_db)):
    count = db.query(Project).count()
    for project in db.query(Project).all():
        db.delete(project)
    db.commit()
    log_event(db, "WARNING", "project", f"Удалены все проекты ({count})")
    return RedirectResponse(f"/?msg=Удалено проектов: {count}", status_code=303)


# ---- bulk actions ---------------------------------------------------------- #
@router.post("/projects/bulk-delete")
async def bulk_delete(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("project_ids")]
    if not ids:
        return RedirectResponse("/?error=Не выбрано ни одного проекта.", status_code=303)
    for project in db.query(Project).filter(Project.id.in_(ids)).all():
        db.delete(project)
    db.commit()
    log_event(db, "WARNING", "project", f"Удалены выбранные проекты ({len(ids)})")
    return RedirectResponse(f"/?msg=Удалено проектов: {len(ids)}", status_code=303)


@router.post("/projects/bulk-strategy")
async def bulk_strategy(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("project_ids")]
    sid = form.get("strategy_id")
    if not ids:
        return RedirectResponse("/?error=Не выбрано ни одного проекта.", status_code=303)
    strategy_id = int(sid) if sid else None
    for project in db.query(Project).filter(Project.id.in_(ids)).all():
        project.strategy_id = strategy_id
    db.commit()
    name = "—"
    if strategy_id:
        s = db.get(Strategy, strategy_id)
        name = s.name if s else "—"
    log_event(db, "INFO", "project", f"Стратегия «{name}» назначена {len(ids)} проектам")
    return RedirectResponse(f"/?msg=Стратегия назначена {len(ids)} проектам", status_code=303)


@router.post("/projects/{pid}/keywords")
async def upload_keywords(pid: int, db: Session = Depends(get_db), file: UploadFile = None):
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    if file is None or not file.filename:
        return RedirectResponse(f"/projects/{pid}?msg=Файл не выбран", status_code=303)
    content = await file.read()
    pairs = parse_frequency(file.filename, content)
    if not pairs:
        log_event(db, "WARNING", "upload", f"Частотка не распознана: {file.filename}",
                  f"Проект {project.url}. Проверьте, что в файле есть колонки keyword и frequency.")
        return RedirectResponse(f"/projects/{pid}?msg=Ошибка: не найдено ключей в файле", status_code=303)
    for kw in list(project.keywords):
        db.delete(kw)
    db.flush()
    for i, (keyword, freq) in enumerate(pairs):
        db.add(Keyword(project_id=pid, keyword=keyword, frequency=freq, position=i))
    db.commit()
    log_event(db, "INFO", "upload", f"Загружена частотка для {project.url}",
              f"Файл: {file.filename}, ключей: {len(pairs)}")
    return RedirectResponse(f"/projects/{pid}?msg=Загружено ключей: {len(pairs)}.", status_code=303)


@router.post("/projects/batch-keywords")
async def batch_keywords(request: Request, db: Session = Depends(get_db)):
    """Import projects from Excel/CSV: one sheet = one project (keywords + freq + domain)."""
    form = await request.form()
    files = [f for f in form.getlist("files") if getattr(f, "filename", "")]
    if not files:
        return RedirectResponse("/?error=Файлы не выбраны.", status_code=303)

    created, updated, skipped, unmatched = [], [], [], []

    def by_url(url: str) -> Project | None:
        return db.query(Project).filter(Project.url == normalize_domain(url)).first()

    def assign(target: Project, pairs: list[tuple[str, float]]) -> None:
        for kw in list(target.keywords):
            db.delete(kw)
        db.flush()
        for i, (keyword, freq) in enumerate(pairs):
            db.add(Keyword(project_id=target.id, keyword=keyword, frequency=freq, position=i))
        db.commit()

    for upload in files:
        content = await upload.read()
        fname = upload.filename
        stem = os.path.splitext(os.path.basename(fname))[0]
        is_excel = fname.lower().endswith((".xlsx", ".xlsm"))
        units = parse_project_sheets(content) if is_excel else [parse_project_table(fname, content)]

        for unit in units:
            label = f"{fname} → «{unit['name']}»" if is_excel else fname
            pairs, domain = unit["pairs"], unit["domain"]
            if not pairs:
                skipped.append(unit["name"])
                continue
            if domain:
                existing = by_url(domain)
                if existing:
                    assign(existing, pairs)
                    updated.append(f"{normalize_domain(domain)} ({len(pairs)} ключей)")
                    log_event(db, "INFO", "import", f"Обновлён проект {normalize_domain(domain)}",
                              f"{label}, ключей: {len(pairs)}")
                else:
                    project = Project(url=normalize_domain(domain), language="English", brand="")
                    db.add(project)
                    db.flush()
                    assign(project, pairs)
                    created.append(f"{project.url} ({len(pairs)} ключей)")
                    log_event(db, "INFO", "import", f"Создан проект {project.url}",
                              f"{label}, ключей: {len(pairs)}")
                continue
            target = match_project(unit["name"] if is_excel else stem, db.query(Project).all())
            if target is None:
                unmatched.append(label)
                log_event(db, "WARNING", "import", f"Не удалось определить проект: {label}",
                          "В листе не найден домен, и имя не совпало ни с одним проектом.")
                continue
            assign(target, pairs)
            updated.append(f"{target.url} ({len(pairs)} ключей)")
            log_event(db, "INFO", "import", f"Обновлён проект {target.url}", f"{label}, ключей: {len(pairs)}")

    parts = [f"Создано проектов: {len(created)}, обновлено: {len(updated)}."]
    if created:
        parts.append("Новые: " + ", ".join(created))
    if unmatched:
        parts.append(f"Без домена и без совпадения ({len(unmatched)}): {', '.join(unmatched)}")
    if skipped:
        parts.append(f"Пропущено пустых/сводных листов: {len(skipped)}")
    parts.append("Детали — на странице «Логи».")
    note = " ".join(parts)
    return RedirectResponse(f"/?{'msg' if (created or updated) else 'error'}={note}", status_code=303)


@router.get("/projects/{pid}/export")
def export_project(pid: int, db: Session = Depends(get_db)):
    """One-click Excel download for a ready project (same file as on Generate)."""
    project = db.get(Project, pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    from ..models import SEO_SPECIALISTS
    sheets = generate_project_sheets(db, project)
    if not sheets:
        return RedirectResponse(f"/projects/{pid}?msg=Нет данных: задайте стратегию, объём и частотку.",
                                status_code=303)
    content = build_workbook(sheets, sprint="", seo_specialist=SEO_SPECIALISTS[0], language=project.language or "")
    record_history(db, project, "separate", sheets)
    log_event(db, "INFO", "generate", f"Выгружен (с вкладки Проекты) {project.url}",
              f"Стратегия: {project.strategy.name if project.strategy else '—'}, объём: {project.volume}")
    db.commit()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename(project.url)}"'},
    )
