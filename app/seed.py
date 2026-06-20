"""Seed the database with base strategies, anchorless profiles and the suffix
dictionary. Idempotent: only inserts when empty. Also runs light SQLite
migrations (adding new columns to existing tables).
"""
from __future__ import annotations

import json

from sqlalchemy import text

from .database import Base, SessionLocal, engine
from .models import AnchorlessProfile, IgnoreAnchor, InternalPageSuffix, Strategy

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

# Default stop-phrases for the smart anchor filter (editable on the dashboard).
BASE_IGNORE_ANCHORS = [
    "login", "no deposit bonus", "no deposit bonus code", "trustpilot",
    "reviews", "free spins", "tv", "youtube", "no deposit",
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
        proj_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(projects)"))}
        if proj_cols and "anchorless_profile_id" not in proj_cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN anchorless_profile_id INTEGER"))
        strat_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(strategies)"))}
        if strat_cols and "anchorless_profile_id" not in strat_cols:
            conn.execute(text("ALTER TABLE strategies ADD COLUMN anchorless_profile_id INTEGER"))
        # Drop stale joke-model overrides so existing DBs pick up the new defaults.
        app_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(app_settings)"))}
        if app_cols:
            conn.execute(text(
                "DELETE FROM app_settings WHERE key IN ('or_model_1','or_model_2') "
                "AND value IN ('meta-llama/llama-3.3-70b-instruct:free',"
                "'deepseek/deepseek-chat-v3.1:free','openai/gpt-4o-mini',"
                "'nvidia/nemotron-3-8b-chat','')"
            ))


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    db = SessionLocal()
    try:
        # Anchorless profiles first — strategies reference the default one.
        if db.query(AnchorlessProfile).count() == 0:
            for p in BASE_PROFILES:
                db.add(AnchorlessProfile(
                    name=p["name"],
                    items_json=json.dumps(p["items"], ensure_ascii=False),
                    is_builtin=True,
                ))
            db.commit()
        default_profile = db.query(AnchorlessProfile).filter_by(name="100% Голый URL").first()
        default_profile_id = default_profile.id if default_profile else None

        if db.query(Strategy).count() == 0:
            for s in BASE_STRATEGIES:
                db.add(
                    Strategy(
                        name=s["name"],
                        anchorless_percent=s["anchorless_percent"],
                        roles_json=json.dumps(s["roles"], ensure_ascii=False),
                        anchorless_profile_id=default_profile_id,
                        is_builtin=True,
                    )
                )
        if db.query(InternalPageSuffix).count() == 0:
            for page_type, langs in BASE_SUFFIXES.items():
                for lang, suffix in langs.items():
                    db.add(InternalPageSuffix(page_type=page_type, language=lang, suffix=suffix))
        if db.query(IgnoreAnchor).count() == 0:
            for phrase in BASE_IGNORE_ANCHORS:
                db.add(IgnoreAnchor(phrase=phrase))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("Seed complete.")
