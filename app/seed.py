"""Seed the database with the base strategies, formats and suffix dictionary
described in the spec (§3.3, §3.5, §3.6). Idempotent: only inserts when empty.
"""
from __future__ import annotations

import json

from .database import Base, SessionLocal, engine
from .models import AnchorlessFormat, InternalPageSuffix, Strategy

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

BASE_FORMATS = [
    # По умолчанию безанкор идёт полным URL (https://site.com/). Дополнительно —
    # голый домен (site.com); пользователь может менять/добавлять форматы.
    {"name": "Голый URL", "template": "{url}", "sub_weight": 60, "position": 0},
    {"name": "Голый домен", "template": "{domain}", "sub_weight": 15, "position": 1},
]

# page_type -> {language -> suffix}. Starter set; editable on the dashboard (§3.6).
BASE_SUFFIXES = {
    "app": {"en": "app", "de": "app", "pl": "aplikacja", "tr": "uygulama", "pt-br": "app"},
    "login": {"en": "login", "de": "login", "pl": "logowanie", "tr": "giris", "pt-br": "login"},
    "bonus": {"en": "bonus", "de": "bonus", "pl": "bonus", "tr": "bonus", "pt-br": "bonus"},
    "withdraw": {"en": "withdraw", "de": "auszahlung", "pl": "wyplata", "tr": "para cekme", "pt-br": "saque"},
    "deposit": {"en": "deposit", "de": "einzahlung", "pl": "wplata", "tr": "para yatirma", "pt-br": "deposito"},
}


def seed() -> None:
    Base.metadata.create_all(bind=engine)
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
        if db.query(AnchorlessFormat).count() == 0:
            for f in BASE_FORMATS:
                db.add(AnchorlessFormat(**f))
        if db.query(InternalPageSuffix).count() == 0:
            for page_type, langs in BASE_SUFFIXES.items():
                for lang, suffix in langs.items():
                    db.add(InternalPageSuffix(page_type=page_type, language=lang, suffix=suffix))
        db.commit()

        # Migration: the old default seeded a Markdown anchorless format, which is
        # not wanted. Convert that untouched default into "Голый домен" ({domain}).
        legacy = (
            db.query(AnchorlessFormat)
            .filter(AnchorlessFormat.template == "[{domain}]({url})", AnchorlessFormat.name == "Markdown-ссылка")
            .first()
        )
        if legacy:
            legacy.name = "Голый домен"
            legacy.template = "{domain}"
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("Seed complete.")
