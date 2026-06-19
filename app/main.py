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
from .models import (
    SUFFIX_LANGUAGES,
    AnchorlessFormat,
    InternalPageSuffix,
    Keyword,
    Project,
    Strategy,
)
from .parsing import parse_frequency
from .seed import seed
from .service import generate_project_sheets

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="Генератор URL-анкоров")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.on_event("startup")
def _startup() -> None:
    seed()


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "projects": db.query(Project).order_by(Project.id).all(),
            "strategies": db.query(Strategy).order_by(Strategy.id).all(),
            "formats": db.query(AnchorlessFormat).order_by(AnchorlessFormat.position).all(),
            "active": "dashboard",
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
        parsed.append({"obj": s, "roles": json.loads(s.roles_json)})
    return templates.TemplateResponse(
        "strategies.html",
        {"request": request, "strategies": parsed, "active": "strategies", "error": error, "msg": msg},
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
    if sid:
        strategy = db.query(Strategy).get(int(sid))
        if not strategy:
            raise HTTPException(404, "Стратегия не найдена")
        strategy.name = name
        strategy.anchorless_percent = anchorless
        strategy.roles_json = roles_json
    else:
        db.add(Strategy(name=name, anchorless_percent=anchorless, roles_json=roles_json))
    db.commit()
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
# Anchorless formats (§3.5)
# --------------------------------------------------------------------------- #
@app.get("/formats", response_class=HTMLResponse)
def formats_page(request: Request, db: Session = Depends(get_db), msg: str = ""):
    return templates.TemplateResponse(
        "formats.html",
        {
            "request": request,
            "formats": db.query(AnchorlessFormat).order_by(AnchorlessFormat.position, AnchorlessFormat.id).all(),
            "active": "formats",
            "msg": msg,
        },
    )


@app.post("/formats/save")
def save_format(
    db: Session = Depends(get_db),
    id: str = Form(""),
    name: str = Form(...),
    template: str = Form("{url}"),
    sub_weight: float = Form(0.0),
    position: int = Form(0),
):
    if id:
        fmt = db.query(AnchorlessFormat).get(int(id))
        if not fmt:
            raise HTTPException(404, "Формат не найден")
        fmt.name, fmt.template, fmt.sub_weight, fmt.position = name, template, sub_weight, position
    else:
        db.add(AnchorlessFormat(name=name, template=template, sub_weight=sub_weight, position=position))
    db.commit()
    return RedirectResponse("/formats?msg=Формат сохранён", status_code=303)


@app.post("/formats/{fid}/delete")
def delete_format(fid: int, db: Session = Depends(get_db)):
    fmt = db.query(AnchorlessFormat).get(fid)
    if fmt:
        db.delete(fmt)
        db.commit()
    return RedirectResponse("/formats", status_code=303)


# --------------------------------------------------------------------------- #
# Internal-page suffix dictionary (§3.6)
# --------------------------------------------------------------------------- #
@app.get("/suffixes", response_class=HTMLResponse)
def suffixes_page(request: Request, db: Session = Depends(get_db), msg: str = ""):
    entries = db.query(InternalPageSuffix).order_by(InternalPageSuffix.page_type, InternalPageSuffix.language).all()
    # Pivot into page_type -> {language -> suffix} for a tidy grid.
    grid: dict[str, dict[str, str]] = {}
    for e in entries:
        grid.setdefault(e.page_type, {})[e.language] = e.suffix
    return templates.TemplateResponse(
        "suffixes.html",
        {
            "request": request,
            "grid": grid,
            "languages": SUFFIX_LANGUAGES,
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
    page_types = sorted({e.page_type for e in db.query(InternalPageSuffix).all()})
    return templates.TemplateResponse(
        "project.html",
        {
            "request": request,
            "project": project,
            "strategies": db.query(Strategy).order_by(Strategy.id).all(),
            "languages": SUFFIX_LANGUAGES,
            "page_types": page_types,
            "internal_pages": json.loads(project.internal_pages_json or "{}"),
            "keywords": project.keywords,
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
    return RedirectResponse(f"/projects/{project.id}?msg=Проект создан", status_code=303)


@app.post("/projects/{pid}/update")
async def update_project(pid: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).get(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    form = await request.form()
    project.url = (form.get("url") or project.url).strip()
    project.language = (form.get("language") or project.language).strip()
    project.brand = (form.get("brand") or "").strip()
    sid = form.get("strategy_id")
    project.strategy_id = int(sid) if sid else None
    project.volume = int(form.get("volume") or 0)
    project.crowd_volume = int(form.get("crowd_volume") or 0)
    project.internal_language = form.get("internal_language") or "en"

    # Internal pages: parallel page_type / path lists.
    page_types = form.getlist("ip_type")
    paths = form.getlist("ip_path")
    internal: dict[str, str] = {}
    for pt, path in zip(page_types, paths):
        pt, path = pt.strip().lower(), path.strip()
        if pt and path:
            internal[pt] = path
    project.internal_pages_json = json.dumps(internal, ensure_ascii=False)

    # Manual redistribution (optional JSON, §4.2).
    redistribution_raw = (form.get("redistribution_json") or "").strip()
    if redistribution_raw:
        try:
            json.loads(redistribution_raw)
            project.redistribution_json = redistribution_raw
        except json.JSONDecodeError:
            return RedirectResponse(f"/projects/{pid}?msg=Ошибка: некорректный JSON перераспределения", status_code=303)
    else:
        project.redistribution_json = "{}"

    db.commit()
    return RedirectResponse(f"/projects/{pid}?msg=Проект сохранён", status_code=303)


@app.post("/projects/{pid}/delete")
def delete_project(pid: int, db: Session = Depends(get_db)):
    project = db.query(Project).get(pid)
    if project:
        db.delete(project)
        db.commit()
    return RedirectResponse("/", status_code=303)


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
        return RedirectResponse(f"/projects/{pid}?msg=Ошибка: не найдено ключей в файле", status_code=303)
    # Replace existing frequency table for this project.
    for kw in list(project.keywords):
        db.delete(kw)
    db.flush()
    for i, (keyword, freq) in enumerate(pairs):
        db.add(Keyword(project_id=pid, keyword=keyword, frequency=freq, position=i))
    db.commit()
    return RedirectResponse(f"/projects/{pid}?msg=Загружено ключей: {len(pairs)}", status_code=303)


# --------------------------------------------------------------------------- #
# Batch frequency upload (§5.2 — несколько файлов пачкой)
# --------------------------------------------------------------------------- #
@app.post("/projects/batch-keywords")
async def batch_keywords(request: Request, db: Session = Depends(get_db)):
    """Upload many frequency files at once. Each file is matched to a project by
    domain substring in the filename; unmatched files are reported."""
    form = await request.form()
    files = form.getlist("files")
    projects = db.query(Project).all()
    matched, unmatched = 0, []
    for upload in files:
        if not getattr(upload, "filename", ""):
            continue
        content = await upload.read()
        stem = os.path.splitext(os.path.basename(upload.filename))[0].lower()
        target = None
        for p in projects:
            from .generator import domain_of

            dom = domain_of(p.url).lower()
            key = dom.split(".")[0] if dom else ""
            if key and key in stem:
                target = p
                break
        if target is None:
            unmatched.append(upload.filename)
            continue
        pairs = parse_frequency(upload.filename, content)
        for kw in list(target.keywords):
            db.delete(kw)
        db.flush()
        for i, (keyword, freq) in enumerate(pairs):
            db.add(Keyword(project_id=target.id, keyword=keyword, frequency=freq, position=i))
        matched += 1
    db.commit()
    note = f"Сопоставлено файлов: {matched}."
    if unmatched:
        note += " Не сопоставлены: " + ", ".join(unmatched)
    return RedirectResponse(f"/?msg={note}", status_code=303)


# --------------------------------------------------------------------------- #
# Generation & export (§6)
# --------------------------------------------------------------------------- #
@app.get("/generate", response_class=HTMLResponse)
def generate_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "generate.html",
        {"request": request, "projects": db.query(Project).order_by(Project.id).all(), "active": "generate"},
    )


@app.get("/projects/{pid}/preview", response_class=HTMLResponse)
def preview(pid: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).get(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    sheets = generate_project_sheets(db, project)
    totals = {name: sum(r.link_qty for r in rows) for name, rows in sheets.items()}
    return templates.TemplateResponse(
        "preview.html",
        {"request": request, "project": project, "sheets": sheets, "totals": totals, "active": "generate"},
    )


@app.post("/generate")
async def generate(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    pids = [int(x) for x in form.getlist("project_ids")]
    export_format = form.get("export_format", "zip")
    if not pids:
        return RedirectResponse("/generate", status_code=303)

    projects = db.query(Project).filter(Project.id.in_(pids)).all()
    files: dict[str, bytes] = {}
    for project in projects:
        sheets = generate_project_sheets(db, project)
        if not sheets:
            continue
        files[safe_filename(project.url)] = build_workbook(sheets)

    if not files:
        return RedirectResponse("/generate", status_code=303)

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


@app.get("/health")
def health():
    return {"status": "ok"}
