"""Bridge between ORM models and the pure generation engine."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from . import generator as gen
from .models import AnchorlessFormat, InternalPageSuffix, Project, Strategy


def strategy_to_gen(strategy: Strategy) -> gen.Strategy:
    roles = [gen.Role(name=r["name"], percent=float(r["percent"])) for r in json.loads(strategy.roles_json)]
    return gen.Strategy(
        name=strategy.name,
        anchorless_percent=float(strategy.anchorless_percent),
        roles=roles,
    )


def load_formats(db: Session) -> list[gen.AnchorlessFormat]:
    formats = db.query(AnchorlessFormat).order_by(AnchorlessFormat.position, AnchorlessFormat.id).all()
    return [gen.AnchorlessFormat(name=f.name, template=f.template, sub_weight=float(f.sub_weight)) for f in formats]


def load_suffix_lookup(db: Session) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for entry in db.query(InternalPageSuffix).all():
        lookup.setdefault(entry.page_type, {})[entry.language] = entry.suffix
    return lookup


def project_to_gen(db: Session, project: Project) -> gen.ProjectInput:
    internal_pages = [
        gen.InternalPage(page_type=pt, url_path=path)
        for pt, path in json.loads(project.internal_pages_json or "{}").items()
    ]
    keywords = [
        gen.KeywordInput(keyword=k.keyword, frequency=float(k.frequency), position=k.position)
        for k in project.keywords
    ]
    return gen.ProjectInput(
        url=project.url,
        article_language=project.language,
        brand=project.brand,
        keywords=keywords,
        internal_pages=internal_pages,
        internal_language=project.internal_language,
        suffix_lookup=load_suffix_lookup(db),
        redistribution=json.loads(project.redistribution_json or "{}"),
    )


def generate_project_sheets(db: Session, project: Project) -> dict[str, list[gen.GeneratedRow]]:
    """Build the three campaign-type sheets for a project (§6)."""
    pin = project_to_gen(db, project)
    formats = load_formats(db)
    sheets: dict[str, list[gen.GeneratedRow]] = {}

    if project.strategy and project.volume > 0:
        strat = strategy_to_gen(project.strategy)
        sheets["Прогоны"] = gen.generate_profile_rows(pin, strat, project.volume, formats)

    if project.crowd_volume > 0:
        sheets["Крауд+сабмиты"] = gen.generate_crowd_rows(pin, project.crowd_volume, formats)

    internal = gen.generate_internal_rows(pin)
    if internal:
        sheets["Внутренние страницы"] = internal

    return sheets
