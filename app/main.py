"""FastAPI application: web dashboard + generation endpoints (§7)."""
from __future__ import annotations

import json
import os

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import generator as gen
from .database import get_db
from .excel_export import build_workbook, build_zip, safe_filename
from .logging_util import log_event
from .models import (
    ARTICLE_LANGUAGES,
    SUFFIX_LANGUAGES,
    AnchorlessProfile,
    History,
    InternalPageSuffix,
    Keyword,
    Log,
    Project,
    Strategy,
)
from .parsing import parse_frequency, parse_project_sheets, parse_project_table
from .seed import seed
from .service import anchorless_summary, generate_project_sheets, profile_example, strategy_label

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="Генератор URL-анкоров")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.on_event("startup")
def _startup() -> None:
    seed()


def _project_progress(project: Project) -> dict:
    """Compute the readiness checklist used to guide the user (UX)."""
    has_keywords = len(project.keywords) > 0
    has_strategy = project.strategy_id is not None
    has_volume = (project.volume or 0) > 0 or (project.crowd_volume or 0) > 0
    ready = has_keywords and has_strategy and has_volume
    return {
        "has_keywords": has_keywords,
        "has_strategy": has_strategy,
        "has_volume": has_volume,
        "ready": ready,
    }


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), msg: str = "", error: str = ""):
    projects = db.query(Project).order_by(Project.id).all()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "projects": projects,
            "progress": {p.id: _project_progress(p) for p in projects},
            "strategies": db.query(Strategy).order_by(Strategy.id).all(),
            "article_languages": ARTICLE_LANGUAGES,
            "active": "dashboard",
            "msg": msg,
            "error": error,
        },
    )


# --------------------------------------------------------------------------- #
# Strategies (§3.3)
# --------------------------------------------------------------------------- #
@app.get("/strategies", response_class=HTMLResponse)
def strategies_page(request: Request, db: Session = Depends(get_db), error: str = "", msg: str = ""):
    strategies = db.query(Strategy).order_by(Strategy.id).all()
    parsed = []
    for s in strategies:
        parsed.append({
            "obj": s,
            "roles": json.loads(s.roles_json),
            "anchorless": anchorless_summary(s),
        })
    return templates.TemplateResponse(
        "strategies.html",
        {
            "request": request,
            "strategies": parsed,
            "anchorless_profiles": db.query(AnchorlessProfile).order_by(AnchorlessProfile.id).all(),
            "active": "strategies",
            "error": error,
            "msg": msg,
        },
    )


def _parse_roles_form(role_names: list[str], role_percents: list[str]) -> list[gen.Role]:
    roles = []
    for name, percent in zip(role_names, role_percents):
        name = name.strip()
        if not name:
            continue
        try:
            roles.append(gen.Role(name=name, percent=float(str(percent).replace(",", "."))))
        except ValueError:
            continue
    return roles


@app.post("/strategies/save")
async def save_strategy(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    sid = form.get("id")
    name = (form.get("name") or "").strip()
    try:
        anchorless = float(str(form.get("anchorless_percent", "0")).replace(",", "."))
    except ValueError:
        anchorless = 0.0
    role_names = form.getlist("role_name")
    role_percents = form.getlist("role_percent")
    roles = _parse_roles_form(role_names, role_percents)

    if not name:
        return RedirectResponse("/strategies?error=Укажите название стратегии", status_code=303)

    err = gen.validate_strategy_sum(anchorless, roles)
    if err:
        return RedirectResponse(f"/strategies?error={err}", status_code=303)

    roles_json = json.dumps([{"name": r.name, "percent": r.percent} for r in roles], ensure_ascii=False)
    apid = form.get("anchorless_profile_id")
    profile_id = int(apid) if apid else None
    if sid:
        strategy = db.query(Strategy).get(int(sid))
        if not strategy:
            raise HTTPException(404, "Стратегия не найдена")
        strategy.name = name
        strategy.anchorless_percent = anchorless
        strategy.roles_json = roles_json
        strategy.anchorless_profile_id = profile_id
        action = "обновлена"
    else:
        db.add(Strategy(name=name, anchorless_percent=anchorless, roles_json=roles_json,
                        anchorless_profile_id=profile_id))
        action = "создана"
    db.commit()
    log_event(db, "INFO", "strategy", f"Стратегия «{name}» {action}",
              f"Безанкор {anchorless}%, ролей: {len(roles)}")
    return RedirectResponse("/strategies?msg=Стратегия сохранена", status_code=303)


@app.post("/strategies/{sid}/delete")
def delete_strategy(sid: int, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).get(sid)
    if strategy:
        # Detach projects that referenced it.
        for p in db.query(Project).filter(Project.strategy_id == sid).all():
            p.strategy_id = None
        db.delete(strategy)
        db.commit()
    return RedirectResponse("/strategies", status_code=303)


# --------------------------------------------------------------------------- #
# Anchorless profiles (saved presets, like strategies)
# --------------------------------------------------------------------------- #
@app.get("/profiles", response_class=HTMLResponse)
def profiles_page(request: Request, db: Session = Depends(get_db), error: str = "", msg: str = ""):
    profiles = db.query(AnchorlessProfile).order_by(AnchorlessProfile.id).all()
    parsed = []
    for p in profiles:
        parsed.append({"obj": p, "formats": json.loads(p.items_json or "[]"), "example": profile_example(p)})
    return templates.TemplateResponse(
        "profiles.html",
        {"request": request, "profiles": parsed, "active": "profiles", "error": error, "msg": msg},
    )


@app.post("/profiles/save")
async def save_profile(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    pid = form.get("id")
    name = (form.get("name") or "").strip()
    names = form.getlist("item_name")
    templates_ = form.getlist("item_template")
    percents = form.getlist("item_percent")
    items = []
    for nm, tpl, pc in zip(names, templates_, percents):
        tpl = (tpl or "").strip()
        if not tpl:
            continue
        try:
            percent = float(str(pc).replace(",", "."))
        except ValueError:
            percent = 0.0
        items.append({"name": (nm or "").strip(), "template": tpl, "percent": percent})

    if not name:
        return RedirectResponse("/profiles?error=Укажите название профиля", status_code=303)
    if not items:
        return RedirectResponse("/profiles?error=Добавьте хотя бы один формат", status_code=303)

    items_json = json.dumps(items, ensure_ascii=False)
    if pid:
        profile = db.query(AnchorlessProfile).get(int(pid))
        if not profile:
            raise HTTPException(404, "Профиль не найден")
        profile.name = name
        profile.items_json = items_json
    else:
        db.add(AnchorlessProfile(name=name, items_json=items_json))
    db.commit()
    log_event(db, "INFO", "anchorless", f"Сохранён безанкорный профиль «{name}»",
              f"Форматов: {len(items)}")
    return RedirectResponse("/profiles?msg=Профиль сохранён", status_code=303)


@app.post("/profiles/{pid}/delete")
def delete_profile(pid: int, db: Session = Depends(get_db)):
    profile = db.query(AnchorlessProfile).get(pid)
    if profile:
        for proj in db.query(Project).filter(Project.anchorless_profile_id == pid).all():
            proj.anchorless_profile_id = None
        db.delete(profile)
        db.commit()
    return RedirectResponse("/profiles", status_code=303)


# --------------------------------------------------------------------------- #
# Internal-page suffix dictionary (§3.6)
# --------------------------------------------------------------------------- #
@app.get("/suffixes", response_class=HTMLResponse)
def suffixes_page(request: Request, db: Session = Depends(get_db), msg: str = "", project: str = ""):
    entries = db.query(InternalPageSuffix).order_by(InternalPageSuffix.page_type, InternalPageSuffix.language).all()
    # Pivot into page_type -> {language -> suffix} for a tidy grid.
    grid: dict[str, dict[str, str]] = {}
    for e in entries:
        grid.setdefault(e.page_type, {})[e.language] = e.suffix

    projects = db.query(Project).order_by(Project.id).all()
    selected = db.query(Project).get(int(project)) if project else None
    page_types = sorted(grid.keys())
    return templates.TemplateResponse(
        "suffixes.html",
        {
            "request": request,
            "grid": grid,
            "languages": SUFFIX_LANGUAGES,
            "projects": projects,
            "selected": selected,
            "selected_internal": json.loads(selected.internal_pages_json or "{}") if selected else {},
            "page_types": page_types,
            "active": "suffixes",
            "msg": msg,
        },
    )


@app.post("/suffixes/save")
async def save_suffix(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    page_type = (form.get("page_type") or "").strip().lower()
    if not page_type:
        return RedirectResponse("/suffixes", status_code=303)
    for lang in SUFFIX_LANGUAGES:
        value = (form.get(f"suffix_{lang}") or "").strip()
        entry = (
            db.query(InternalPageSuffix)
            .filter_by(page_type=page_type, language=lang)
            .first()
        )
        if value:
            if entry:
                entry.suffix = value
            else:
                db.add(InternalPageSuffix(page_type=page_type, language=lang, suffix=value))
        elif entry:
            db.delete(entry)
    db.commit()
    log_event(db, "INFO", "suffix", f"Обновлён справочник суффиксов: «{page_type}»")
    return RedirectResponse("/suffixes?msg=Справочник обновлён", status_code=303)


@app.post("/suffixes/{page_type}/delete")
def delete_suffix(page_type: str, db: Session = Depends(get_db)):
    for e in db.query(InternalPageSuffix).filter_by(page_type=page_type).all():
        db.delete(e)
    db.commit()
    return RedirectResponse("/suffixes", status_code=303)


# --------------------------------------------------------------------------- #
# Projects (§3.1, §5)
# --------------------------------------------------------------------------- #
@app.get("/projects/{pid}", response_class=HTMLResponse)
def project_page(pid: int, request: Request, db: Session = Depends(get_db), msg: str = ""):
    project = db.query(Project).get(pid)
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
            "progress": _project_progress(project),
            "active": "dashboard",
            "msg": msg,
        },
    )


@app.post("/projects/create")
def create_project(
    db: Session = Depends(get_db),
    url: str = Form(...),
    language: str = Form("English"),
    brand: str = Form(""),
):
    project = Project(url=url.strip(), language=language.strip(), brand=brand.strip())
    db.add(project)
    db.commit()
    log_event(db, "INFO", "project", f"Создан проект {project.url}", f"Бренд: {project.brand or '—'}")
    return RedirectResponse(f"/projects/{project.id}?msg=Проект создан", status_code=303)


@app.post("/projects/{pid}/basics")
async def update_basics(pid: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).get(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    form = await request.form()
    project.url = (form.get("url") or project.url).strip()
    # Empty language means "do not include in export" — keep the empty value as-is.
    project.language = (form.get("language") or "").strip()
    project.brand = (form.get("brand") or "").strip()
    db.commit()
    log_event(db, "INFO", "project", f"Обновлены параметры проекта {project.url}",
              f"Язык: {project.language or '— не указан —'}, бренд: {project.brand or '—'}")
    return RedirectResponse(f"/projects/{pid}?msg=Основные параметры сохранены", status_code=303)


@app.post("/projects/{pid}/volume")
def update_volume(pid: int, db: Session = Depends(get_db), volume: int = Form(0)):
    project = db.query(Project).get(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    project.volume = max(0, int(volume or 0))
    db.commit()
    log_event(db, "INFO", "project", f"Объём проекта {project.url} → {project.volume}")
    return RedirectResponse(f"/projects/{pid}?msg=Объём сохранён", status_code=303)


@app.post("/projects/{pid}/redistribution")
def update_redistribution(pid: int, db: Session = Depends(get_db), redistribution_json: str = Form("")):
    project = db.query(Project).get(pid)
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


@app.post("/projects/{pid}/internal")
async def update_internal_pages(pid: int, request: Request, db: Session = Depends(get_db)):
    """Per-project internal pages (language + page_type→path). Lives on the
    "Внутренние страницы" section now."""
    project = db.query(Project).get(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    form = await request.form()
    project.internal_language = form.get("internal_language") or "en"
    page_types = form.getlist("ip_type")
    paths = form.getlist("ip_path")
    internal: dict[str, str] = {}
    for pt, path in zip(page_types, paths):
        pt, path = pt.strip().lower(), path.strip()
        if pt and path:
            internal[pt] = path
    project.internal_pages_json = json.dumps(internal, ensure_ascii=False)
    db.commit()
    log_event(db, "INFO", "suffix", f"Внутренние страницы проекта {project.url} обновлены",
              f"Страниц: {len(internal)}, язык: {project.internal_language}")
    return RedirectResponse(f"/suffixes?project={pid}&msg=Внутренние страницы проекта сохранены", status_code=303)


@app.post("/projects/{pid}/delete")
def delete_project(pid: int, db: Session = Depends(get_db)):
    project = db.query(Project).get(pid)
    if project:
        url = project.url
        db.delete(project)
        db.commit()
        log_event(db, "WARNING", "project", f"Удалён проект {url}")
    return RedirectResponse("/", status_code=303)


@app.post("/projects/delete-all")
def delete_all_projects(db: Session = Depends(get_db)):
    count = db.query(Project).count()
    for project in db.query(Project).all():
        db.delete(project)
    db.commit()
    log_event(db, "WARNING", "project", f"Удалены все проекты ({count})")
    return RedirectResponse(f"/?msg=Удалено проектов: {count}", status_code=303)


@app.post("/projects/{pid}/keywords")
async def upload_keywords(pid: int, db: Session = Depends(get_db), file: UploadFile = None):
    project = db.query(Project).get(pid)
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
    # Replace existing frequency table for this project.
    for kw in list(project.keywords):
        db.delete(kw)
    db.flush()
    for i, (keyword, freq) in enumerate(pairs):
        db.add(Keyword(project_id=pid, keyword=keyword, frequency=freq, position=i))
    db.commit()
    log_event(db, "INFO", "upload", f"Загружена частотка для {project.url}",
              f"Файл: {file.filename}, ключей: {len(pairs)}")
    return RedirectResponse(f"/projects/{pid}?msg=Загружено ключей: {len(pairs)}. "
                            f"Дальше: выберите стратегию и объёмы ниже, затем нажмите «Превью» или «Генерация».",
                            status_code=303)


# --------------------------------------------------------------------------- #
# Batch frequency upload (§5.2 — несколько файлов пачкой)
# --------------------------------------------------------------------------- #
def _norm(value: str) -> str:
    """Lowercase and keep only alphanumerics — for fuzzy filename↔project matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _match_project(stem: str, projects: list[Project]) -> Project | None:
    """Match a file (by name) to a project by domain / brand substring, both ways."""
    from .generator import domain_of

    norm_stem = _norm(stem)
    if not norm_stem:
        return None
    best = None
    best_len = 0
    for p in projects:
        candidates = [domain_of(p.url), domain_of(p.url).split(".")[0], p.brand]
        for cand in candidates:
            nc = _norm(cand)
            if not nc or len(nc) < 3:
                continue
            if nc in norm_stem or norm_stem in nc:
                if len(nc) > best_len:  # prefer the most specific match
                    best, best_len = p, len(nc)
    return best


@app.post("/projects/batch-keywords")
async def batch_keywords(request: Request, db: Session = Depends(get_db)):
    """Import projects from uploaded Excel/CSV files.

    One sheet = one project. A sheet carries everything: keywords, frequency and
    the domain (in a header cell, a column, or repeated per row). Column names
    may be synonyms and sit in any position; a KD column is ignored. Empty and
    summary/dashboard sheets are skipped. Domains in ``http://`` form are
    converted to ``https://``. Projects are created or updated (matched by URL);
    if a sheet has no domain, we fall back to matching an existing project by
    the sheet/file name. Per-sheet details go to the Logs page.
    """
    from .parsing import normalize_domain  # local import to avoid clutter at top

    form = await request.form()
    files = [f for f in form.getlist("files") if getattr(f, "filename", "")]
    if not files:
        return RedirectResponse("/?error=Файлы не выбраны.", status_code=303)

    created, updated, skipped, unmatched = [], [], [], []

    def by_url(url: str) -> Project | None:
        norm = normalize_domain(url)
        return db.query(Project).filter(Project.url == norm).first()

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
            pairs = unit["pairs"]
            domain = unit["domain"]

            if not pairs:
                skipped.append(unit["name"])
                continue  # empty / summary / dashboard sheet — silently skipped

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

            # No domain in the sheet -> try matching an existing project by name.
            target = _match_project(unit["name"] if is_excel else stem, db.query(Project).all())
            if target is None:
                unmatched.append(label)
                log_event(db, "WARNING", "import", f"Не удалось определить проект: {label}",
                          "В листе не найден домен, и имя листа/файла не совпало ни с одним проектом. "
                          "Добавьте колонку/ячейку с доменом или переименуйте лист.")
                continue
            assign(target, pairs)
            updated.append(f"{target.url} ({len(pairs)} ключей)")
            log_event(db, "INFO", "import", f"Обновлён проект {target.url}",
                      f"{label}, ключей: {len(pairs)}")

    parts = [f"Создано проектов: {len(created)}, обновлено: {len(updated)}."]
    if created:
        parts.append("Новые: " + ", ".join(created))
    if unmatched:
        parts.append(f"Без домена и без совпадения ({len(unmatched)}): {', '.join(unmatched)}")
    if skipped:
        parts.append(f"Пропущено пустых/сводных листов: {len(skipped)}")
    parts.append("Детали — на странице «Логи».")
    note = " ".join(parts)
    key = "msg" if (created or updated) else "error"
    return RedirectResponse(f"/?{key}={note}", status_code=303)


# --------------------------------------------------------------------------- #
# Generation & export (§6)
# --------------------------------------------------------------------------- #
@app.get("/generate", response_class=HTMLResponse)
def generate_page(request: Request, db: Session = Depends(get_db), msg: str = "", error: str = ""):
    projects = db.query(Project).order_by(Project.id).all()
    strategies = db.query(Strategy).order_by(Strategy.id).all()
    strategy_options = [{"id": s.id, "label": strategy_label(s)} for s in strategies]
    return templates.TemplateResponse(
        "generate.html",
        {
            "request": request,
            "projects": projects,
            "progress": {p.id: _project_progress(p) for p in projects},
            "strategy_options": strategy_options,
            "active": "generate",
            "msg": msg,
            "error": error,
        },
    )


@app.post("/projects/{pid}/strategy")
def set_project_strategy(pid: int, db: Session = Depends(get_db),
                         strategy_id: str = Form(""), next: str = Form("/generate")):
    """Set a project's strategy inline (from the Generate or Project page)."""
    project = db.query(Project).get(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    project.strategy_id = int(strategy_id) if strategy_id else None
    db.commit()
    name = project.strategy.name if project.strategy else "—"
    log_event(db, "INFO", "project", f"Стратегия проекта {project.url} → {name}")
    target = next if next.startswith("/") else "/generate"
    return RedirectResponse(target, status_code=303)


@app.get("/projects/{pid}/preview", response_class=HTMLResponse)
def preview(pid: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).get(pid)
    if not project:
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


@app.post("/generate")
async def generate(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    pids = [int(x) for x in form.getlist("project_ids")]
    export_format = form.get("export_format", "zip")
    if not pids:
        return RedirectResponse("/generate?error=Выберите хотя бы один проект.", status_code=303)

    projects = db.query(Project).filter(Project.id.in_(pids)).all()
    files: dict[str, bytes] = {}
    for project in projects:
        sheets = generate_project_sheets(db, project)
        if not sheets:
            continue
        include_language = bool((project.language or "").strip())
        files[safe_filename(project.url)] = build_workbook(sheets, include_language=include_language)

        # Record History (§ "история": what / how / by which strategy).
        sheet_summary = {name: {"rows": len(rows), "links": sum(r.link_qty for r in rows)}
                         for name, rows in sheets.items()}
        rows_total = sum(s["links"] for s in sheet_summary.values())
        db.add(History(
            project_url=project.url,
            brand=project.brand or "",
            language=project.language or "",
            strategy_name=project.strategy.name if project.strategy else "—",
            volume=project.volume or 0,
            crowd_volume=0,
            export_format=export_format,
            rows_total=rows_total,
            sheets_json=json.dumps(sheet_summary, ensure_ascii=False),
        ))
        log_event(db, "INFO", "generate", f"Сгенерирован {project.url}",
                  f"Стратегия: {project.strategy.name if project.strategy else '—'}, "
                  f"формат: {export_format}, вкладки: {', '.join(sheet_summary)}, всего ссылок: {rows_total}")
    db.commit()

    if not files:
        log_event(db, "WARNING", "generate", "Генерация без результата",
                  "У выбранных проектов нет данных: задайте стратегию, объёмы и загрузите частотку.")
        return RedirectResponse("/generate?error=Нет данных для генерации. "
                                "Проверьте стратегию, объёмы и частотку у выбранных проектов.",
                                status_code=303)

    # Single project, or user chose separate files but only one resulted -> .xlsx
    if len(files) == 1 and export_format != "zip":
        filename, content = next(iter(files.items()))
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    zip_bytes = build_zip(files)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="anchor-plans.zip"'},
    )


# --------------------------------------------------------------------------- #
# History (saved generation records)
# --------------------------------------------------------------------------- #
@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db), msg: str = ""):
    records = db.query(History).order_by(History.created_at.desc(), History.id.desc()).limit(500).all()
    parsed = []
    for r in records:
        parsed.append({"obj": r, "sheets": json.loads(r.sheets_json or "{}")})
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "records": parsed, "active": "history", "msg": msg},
    )


@app.post("/history/clear")
def clear_history(db: Session = Depends(get_db)):
    db.query(History).delete()
    db.commit()
    log_event(db, "WARNING", "history", "История очищена")
    return RedirectResponse("/history?msg=История очищена", status_code=303)


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #
@app.get("/logs", response_class=HTMLResponse)
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


@app.post("/logs/clear")
def clear_logs(db: Session = Depends(get_db)):
    db.query(Log).delete()
    db.commit()
    log_event(db, "WARNING", "logs", "Логи очищены")
    return RedirectResponse("/logs?msg=Логи очищены", status_code=303)


@app.get("/api/joke")
def api_joke():
    from .jokes import get_joke
    return {"joke": get_joke()}


@app.get("/favicon.ico")
def favicon():
    # Browsers probe /favicon.ico at the root; point them at the SVG icon.
    return RedirectResponse("/static/favicon.svg", status_code=307)


@app.get("/health")
def health():
    return {"status": "ok"}
