"""Small shared helpers used across routers (no FastAPI/route logic here)."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .generator import domain_of
from .models import History, Project
from .service import strategy_segments


def project_progress(project: Project) -> dict:
    """Readiness checklist used to guide the user (UX)."""
    has_keywords = len(project.keywords) > 0
    has_strategy = project.strategy_id is not None
    has_volume = (project.volume or 0) > 0
    ready = has_keywords and has_strategy and has_volume
    return {
        "has_keywords": has_keywords,
        "has_strategy": has_strategy,
        "has_volume": has_volume,
        "ready": ready,
    }


def lang_label(language: str) -> str:
    return language if language else "без языка"


def project_view(project: Project) -> dict:
    """Presentation data for a project card."""
    return {
        "obj": project,
        "strategy_name": project.strategy.name if project.strategy else "—",
        "lang_label": lang_label(project.language),
        "segments": strategy_segments(project.strategy) if project.strategy else [],
    }


def record_history(db: Session, project: Project, export_format: str, sheets: dict) -> None:
    """Save a History row for one generated/exported project."""
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


def norm_token(value: str) -> str:
    """Lowercase, alphanumerics only — for fuzzy filename↔project matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def match_project(stem: str, projects: list[Project]) -> Project | None:
    """Match a file/sheet name to a project by domain / brand substring."""
    norm_stem = norm_token(stem)
    if not norm_stem:
        return None
    best, best_len = None, 0
    for p in projects:
        for cand in (domain_of(p.url), domain_of(p.url).split(".")[0], p.brand):
            nc = norm_token(cand)
            if not nc or len(nc) < 3:
                continue
            if (nc in norm_stem or norm_stem in nc) and len(nc) > best_len:
                best, best_len = p, len(nc)
    return best
