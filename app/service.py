"""Bridge between ORM models and the pure generation engine."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from . import generator as gen
from .models import AnchorlessProfile, InternalPageSuffix, Project, Strategy


def strategy_to_gen(strategy: Strategy) -> gen.Strategy:
    roles = [gen.Role(name=r["name"], percent=float(r["percent"])) for r in json.loads(strategy.roles_json)]
    return gen.Strategy(
        name=strategy.name,
        anchorless_percent=float(strategy.anchorless_percent),
        roles=roles,
    )


def profile_to_formats(profile: AnchorlessProfile | None) -> list[gen.AnchorlessFormat]:
    """Convert a saved anchorless profile into engine formats.

    With no profile selected, anchorless falls back to a single bare URL.
    """
    if profile is None:
        return [gen.AnchorlessFormat(name="Голый URL", template="{url}", sub_weight=100)]
    items = json.loads(profile.items_json or "[]")
    formats = [
        gen.AnchorlessFormat(name=i.get("name", ""), template=i["template"], sub_weight=float(i.get("percent", 0)))
        for i in items
        if i.get("template")
    ]
    return formats or [gen.AnchorlessFormat(name="Голый URL", template="{url}", sub_weight=100)]


def formats_for_project(db: Session, project: Project) -> list[gen.AnchorlessFormat]:
    return profile_to_formats(project.anchorless_profile)


def profile_example(profile: AnchorlessProfile, sample: int = 100,
                    url: str = "https://betalice.com/") -> list[dict]:
    """Show how a profile splits ``sample`` anchorless links for an example URL."""
    formats = profile_to_formats(profile)
    rendered = gen.split_anchorless(sample, formats, url)
    # Map rendered string back to a friendly format name (by order).
    names = [f.name for f in formats]
    out = []
    for i, (text, count) in enumerate(rendered):
        out.append({
            "name": names[i] if i < len(names) else "",
            "example": text,
            "count": count,
            "percent": round(count / sample * 100) if sample else 0,
        })
    return out


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
    formats = formats_for_project(db, project)
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
