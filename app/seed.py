"""Seed the database with base strategies, anchorless profiles and the suffix
dictionary. Idempotent: only inserts when empty. Also runs light SQLite
migrations (adding new columns to existing tables).
"""
from __future__ import annotations

import json

from sqlalchemy import text

from .database import Base, SessionLocal, engine
from .models import AnchorlessProfile, InternalPageSuffix, Strategy

BASE_STRATEGIES = [
    {
        "name": "Обычная",
        "anchorless_percent": 70,
        "roles": [
            {"name": "основной 1", "percent": 12},
            {"name": "основной 2", "percent": 9},
            {"name": "добавочный 1", "percent": 5},
            {"name": "добавочный 2", "percent": 4},
        ],
    },
    {
        "name": "Безопасная",
        "anchorless_percent": 75,
        "roles": [
            {"name": "основной 1", "percent": 13},
            {"name": "основной 2", "percent": 5},
            {"name": "добавочный 1", "percent": 4},
            {"name": "добавочный 2", "percent": 3},
        ],
    },
    {
        # Campaign type "крауд + сабмиты" = 100% anchorless (§3.4).
        "name": "Крауд + сабмиты",
        "anchorless_percent": 100,
        "roles": [],
    },
]

# Saved anchorless profiles (like strategies, but for anchorless link formats).
# Percents are relative weights for splitting the anchorless share.
BARE_URL = {"name": "Голый URL", "template": "{url}"}
BARE_DOMAIN = {"name": "Голый домен", "template": "{domain}"}

BASE_PROFILES = [
    {
        "name": "100% Голый URL",
        "items": [{**BARE_URL, "percent": 100}],
    },
    {
        "name": "Голый URL 60% + Голый домен 10%",
        "items": [{**BARE_URL, "percent": 60}, {**BARE_DOMAIN, "percent": 10}],
    },
    {
        "name": "Голый домен 60% + Голый URL 15%",
        "items": [{**BARE_DOMAIN, "percent": 60}, {**BARE_URL, "percent": 15}],
    },
]

# page_type -> {language -> suffix}. Starter set; editable on the dashboard (§3.6).
BASE_SUFFIXES = {
    "app": {"en": "app", "de": "app", "pl": "aplikacja", "tr": "uygulama", "pt-br": "app"},
    "login": {"en": "login", "de": "login", "pl": "logowanie", "tr": "giris", "pt-br": "login"},
    "bonus": {"en": "bonus", "de": "bonus", "pl": "bonus", "tr": "bonus", "pt-br": "bonus"},
    "withdraw": {"en": "withdraw", "de": "auszahlung", "pl": "wyplata", "tr": "para cekme", "pt-br": "saque"},
    "deposit": {"en": "deposit", "de": "einzahlung", "pl": "wplata", "tr": "para yatirma", "pt-br": "deposito"},
}


def _migrate_schema() -> None:
    """Add columns introduced after the first release (SQLite ADD COLUMN)."""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(projects)"))}
        if "anchorless_profile_id" in cols:
            return
        if cols:  # table exists but lacks the column
            conn.execute(text("ALTER TABLE projects ADD COLUMN anchorless_profile_id INTEGER"))


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    db = SessionLocal()
    try:
        if db.query(Strategy).count() == 0:
            for s in BASE_STRATEGIES:
                db.add(
                    Strategy(
                        name=s["name"],
                        anchorless_percent=s["anchorless_percent"],
                        roles_json=json.dumps(s["roles"], ensure_ascii=False),
                        is_builtin=True,
                    )
                )
        if db.query(AnchorlessProfile).count() == 0:
            for p in BASE_PROFILES:
                db.add(AnchorlessProfile(
                    name=p["name"],
                    items_json=json.dumps(p["items"], ensure_ascii=False),
                    is_builtin=True,
                ))
        if db.query(InternalPageSuffix).count() == 0:
            for page_type, langs in BASE_SUFFIXES.items():
                for lang, suffix in langs.items():
                    db.add(InternalPageSuffix(page_type=page_type, language=lang, suffix=suffix))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("Seed complete.")
