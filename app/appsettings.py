"""Runtime app settings: one OpenRouter API key + a model chosen per action.

Everything is edited from the Settings block on the Projects page and stored in
SQLite. Each LLM-backed action picks its own model, with a recommended default:

* ``jokes``          — SEO jokes in the topbar (cheap/fast).
* ``smart``          — semantic stop-anchor matching for the smart filter.
* ``types``          — company 7-type anchor classification (accuracy matters).
* ``schedule_smart`` — anchor typing for the date-distribution tab.
* ``schedule_cheap`` — cheap fallback for date distribution.
"""
from __future__ import annotations

import os

from sqlalchemy.orm import Session

from .models import AppSetting

# Actions that use a model, their label and the model we recommend for each.
ACTIONS = ["jokes", "smart", "types", "schedule_smart", "schedule_cheap"]
ACTION_LABELS = {
    "jokes": "Шутки в шапке",
    "smart": "Умный фильтр (стоп-анкоры, по смыслу)",
    "types": "Определение типов анкоров (7 типов)",
    "schedule_smart": "Распределение по датам — основная",
    "schedule_cheap": "Распределение по датам — запасная (дешёвая)",
}
RECOMMENDED = {
    "jokes": "openai/gpt-4o-mini",          # short, creative, frequent -> cheap & fast
    "smart": "openai/gpt-4o-mini",          # short-phrase semantic match -> cheap is enough
    "types": "openai/gpt-4o",               # rubric classification, few uniques -> accuracy
    "schedule_smart": "openai/gpt-4o",      # few unique anchors -> afford the strong model
    "schedule_cheap": "openai/gpt-4o-mini", # fallback only
}

# Legacy setting keys we still read so previously-saved keys keep working.
_LEGACY_KEYS = ("or_key", "or_key_1", "or_key_2", "or_key_schedule")


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


# --------------------------------------------------------------------------- #
# Unified key + per-action model
# --------------------------------------------------------------------------- #
def get_key(db: Session) -> str:
    """The single OpenRouter key (new setting, else a legacy one, else env)."""
    for k in _LEGACY_KEYS:
        v = get_setting(db, k, "").strip()
        if v:
            return v
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def set_key(db: Session, value: str) -> None:
    set_setting(db, "or_key", (value or "").strip())


def has_key(db: Session) -> bool:
    return bool(get_key(db))


def masked_key(db: Session) -> str:
    k = get_key(db)
    return ("…" + k[-4:]) if len(k) >= 4 else ("задан" if k else "")


def get_action_model(db: Session, action: str) -> str:
    """Model id for an action (user override, else the recommended default)."""
    return get_setting(db, f"model_{action}", "").strip() or RECOMMENDED.get(action, "")


def set_action_model(db: Session, action: str, value: str) -> None:
    set_setting(db, f"model_{action}", (value or "").strip())


def get_models(db: Session) -> dict[str, str]:
    return {a: get_action_model(db, a) for a in ACTIONS}


def get_action_slot(db: Session, action: str) -> tuple[str, str] | None:
    """``(key, model)`` for an action, or ``None`` when no key is configured."""
    key = get_key(db)
    return (key, get_action_model(db, action)) if key else None


# --------------------------------------------------------------------------- #
# Back-compat helpers used across the app
# --------------------------------------------------------------------------- #
def get_slots(db: Session) -> list[tuple[str, str]]:
    """Jokes slots (single unified key + jokes model)."""
    slot = get_action_slot(db, "jokes")
    return [slot] if slot else []


def get_any_slot(db: Session) -> tuple[str, str] | None:
    return get_action_slot(db, "types")


def get_schedule_model(db: Session) -> str:
    return get_action_model(db, "schedule_smart")


def get_schedule_cheap_model(db: Session) -> str:
    return get_action_model(db, "schedule_cheap")


def get_schedule_key(db: Session) -> str:
    return get_key(db)


def get_schedule_slot(db: Session) -> tuple[str, str] | None:
    return get_action_slot(db, "schedule_smart")


def get_schedule_cheap_slot(db: Session) -> tuple[str, str] | None:
    key = get_key(db)
    cheap = get_schedule_cheap_model(db)
    if key and cheap and cheap != get_schedule_model(db):
        return key, cheap
    return None
