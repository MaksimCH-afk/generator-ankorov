"""Core link-plan generation logic (§4).

The functions here are pure (no DB, no I/O) so they are deterministic and easy
to unit-test (§9: same input -> same output). The web layer feeds plain
dataclasses / dicts in and gets row lists back.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse


# --------------------------------------------------------------------------- #
# Input value objects
# --------------------------------------------------------------------------- #
@dataclass
class Role:
    name: str
    percent: float


@dataclass
class Strategy:
    name: str
    anchorless_percent: float
    roles: list[Role]


@dataclass
class AnchorlessFormat:
    name: str
    template: str          # may contain {url} and {domain}
    sub_weight: float      # percent of total volume


@dataclass
class KeywordInput:
    keyword: str
    frequency: float
    position: int = 0      # original file order, tie-break


@dataclass
class GeneratedRow:
    """One output line (§6)."""

    link_qty: int
    url: str
    anchor: str
    article_language: str
    keyword: str


@dataclass
class InternalPage:
    page_type: str
    url_path: str


@dataclass
class ProjectInput:
    url: str
    article_language: str
    brand: str
    keywords: list[KeywordInput] = field(default_factory=list)
    internal_pages: list[InternalPage] = field(default_factory=list)
    internal_language: str = "en"
    # page_type -> {language -> suffix}
    suffix_lookup: dict[str, dict[str, str]] = field(default_factory=dict)
    # role name -> {target role name -> share%}, optional manual redistribution (§4.2)
    redistribution: dict[str, dict[str, float]] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def round_half_up(value: float) -> int:
    """Deterministic round-half-up (Python's ``round`` is banker's rounding)."""
    return int(math.floor(value + 0.5))


def domain_of(url: str) -> str:
    """Return the host part of a URL without scheme or trailing slash."""
    parsed = urlparse(url if "//" in url else "//" + url)
    host = parsed.netloc or parsed.path
    return host.strip("/")


def assign_roles(keywords: list[KeywordInput], roles: list[Role]) -> dict[str, Optional[KeywordInput]]:
    """Map each strategy role to a keyword (§4.4).

    Keywords are sorted by frequency descending; ties keep original file order.
    Extra keywords beyond the number of roles are ignored. Roles without a
    keyword map to ``None`` (treated as "missing", §4.2).
    """
    ordered = sorted(keywords, key=lambda k: (-k.frequency, k.position))
    mapping: dict[str, Optional[KeywordInput]] = {}
    for idx, role in enumerate(roles):
        mapping[role.name] = ordered[idx] if idx < len(ordered) else None
    return mapping


# --------------------------------------------------------------------------- #
# Anchorless diversification (§4.3)
# --------------------------------------------------------------------------- #
def split_anchorless(total: int, formats: list[AnchorlessFormat], url: str) -> list[tuple[str, int]]:
    """Split ``total`` anchorless links across formats by relative sub-weight.

    The last format absorbs the rounding remainder so the sum always equals
    ``total`` (§4.1.3). If no formats are configured, everything becomes the
    bare URL (§4.3). Returns a list of ``(rendered_anchor, count)``.
    """
    if total <= 0:
        return []

    dom = domain_of(url)
    if not formats:
        return [(url, total)]

    weight_sum = sum(f.sub_weight for f in formats)
    if weight_sum <= 0:
        return [(url, total)]

    result: list[tuple[str, int]] = []
    allocated = 0
    for i, fmt in enumerate(formats):
        rendered = fmt.template.format(url=url, domain=dom)
        if i == len(formats) - 1:
            count = total - allocated  # last absorbs remainder
        else:
            count = round_half_up(fmt.sub_weight / weight_sum * total)
            allocated += count
        if count > 0:
            result.append((rendered, count))
    return result


# --------------------------------------------------------------------------- #
# Main per-URL generation (§4.1, §4.2)
# --------------------------------------------------------------------------- #
def generate_profile_rows(
    project: ProjectInput,
    strategy: Strategy,
    volume: int,
    formats: list[AnchorlessFormat],
) -> list[GeneratedRow]:
    """Generate rows for a full anchor profile ("прогоны") for one URL."""
    if volume <= 0:
        return []

    role_to_kw = assign_roles(project.keywords, strategy.roles)

    # Effective anchorless percent starts from the strategy value and grows when
    # a role has no keyword and its weight is not manually redistributed (§4.2).
    anchorless_percent = strategy.anchorless_percent
    # Extra percent pushed onto present roles via manual redistribution.
    extra_role_percent: dict[str, float] = {r.name: 0.0 for r in strategy.roles}

    for role in strategy.roles:
        if role_to_kw.get(role.name) is not None:
            continue
        # role is missing -> redistribute its weight
        manual = project.redistribution.get(role.name)
        if not manual:
            anchorless_percent += role.percent
            continue
        share_sum = sum(manual.values())
        for target, share in manual.items():
            if share_sum <= 0:
                continue
            portion = role.percent * (share / share_sum)
            if target in extra_role_percent and role_to_kw.get(target) is not None:
                extra_role_percent[target] += portion
            else:
                # target missing/unknown -> fall back to anchorless
                anchorless_percent += portion

    rows: list[GeneratedRow] = []
    anchor_total = 0
    for role in strategy.roles:
        kw = role_to_kw.get(role.name)
        if kw is None:
            continue
        percent = role.percent + extra_role_percent.get(role.name, 0.0)
        count = round_half_up(percent / 100.0 * volume)
        if count <= 0:
            continue
        anchor_total += count
        rows.append(
            GeneratedRow(
                link_qty=count,
                url=project.url,
                anchor=kw.keyword,
                article_language=project.article_language,
                keyword=kw.keyword,
            )
        )

    # Anchorless absorbs the rounding remainder so the total equals volume (§4.1.2).
    anchorless_count = volume - anchor_total
    if anchorless_count < 0:
        anchorless_count = 0

    anchorless_rows = split_anchorless(anchorless_count, formats, project.url)
    # Anchorless rows come first, matching the example output ordering (§6).
    prefix = [
        GeneratedRow(
            link_qty=count,
            url=project.url,
            anchor=rendered,
            article_language=project.article_language,
            keyword=rendered,
        )
        for rendered, count in anchorless_rows
    ]
    return prefix + rows


def generate_crowd_rows(
    project: ProjectInput,
    volume: int,
    formats: list[AnchorlessFormat],
) -> list[GeneratedRow]:
    """Generate rows for the "крауд + сабмиты" campaign: 100% anchorless (§3.4)."""
    if volume <= 0:
        return []
    return [
        GeneratedRow(
            link_qty=count,
            url=project.url,
            anchor=rendered,
            article_language=project.article_language,
            keyword=rendered,
        )
        for rendered, count in split_anchorless(volume, formats, project.url)
    ]


def generate_internal_rows(project: ProjectInput) -> list[GeneratedRow]:
    """Generate one fixed-anchor row per internal page (§4.5).

    Anchor = ``{brand} {suffix}`` where suffix comes from the dictionary for the
    page type and the project's chosen internal language. URL = root + path.
    """
    rows: list[GeneratedRow] = []
    root = project.url.rstrip("/")
    for page in project.internal_pages:
        suffix = project.suffix_lookup.get(page.page_type, {}).get(project.internal_language, "")
        anchor = f"{project.brand} {suffix}".strip()
        path = page.url_path
        if not path.startswith("/"):
            path = "/" + path
        full_url = root + path
        rows.append(
            GeneratedRow(
                link_qty=1,
                url=full_url,
                anchor=anchor,
                article_language=project.article_language,
                keyword=anchor,
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Validation (§9)
# --------------------------------------------------------------------------- #
def validate_strategy_sum(anchorless_percent: float, roles: list[Role], tol: float = 0.01) -> Optional[str]:
    """Return an error message if anchorless + roles != 100, else ``None``."""
    total = anchorless_percent + sum(r.percent for r in roles)
    if abs(total - 100.0) > tol:
        return f"Сумма весов стратегии = {total:g}%, должна быть 100%."
    return None
