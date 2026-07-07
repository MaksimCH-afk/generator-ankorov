"""Runtime app settings (OpenRouter keys for the joke widget).

Two key slots, each routed to a different model so we can alternate (round-robin)
and dodge a single model's rate limits / timeouts. Keys are added at runtime via
the discreet panel on the Logs page and stored in SQLite.
"""
from __future__ import annotations

import os

from sqlalchemy.orm import Session

from .models import AppSetting

# Default model per slot (overridable per slot from the Logs page).
# Free OpenRouter models — work with any valid OpenRouter key.
DEFAULT_MODELS = {
    1: "nvidia/nemotron-3-ultra-550b-a55b:free",
    2: "qwen/qwen3-next-80b-a3b-instruct:free",
}

# Date-distribution tab. Only the *distinct* anchors are classified (usually a
# handful even for thousands of links), so we can afford a strong "smart" model
# for them and fall back to a cheap model only if the smart one fails.
SCHEDULE_DEFAULT_MODEL = "openai/gpt-4o"        # smart (few unique anchors -> cheap overall)
SCHEDULE_CHEAP_MODEL = "openai/gpt-4o-mini"     # fallback


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


def get_model(db: Session, slot: int) -> str:
    """Model id for a slot (user override, else the default)."""
    return get_setting(db, f"or_model_{slot}", "").strip() or DEFAULT_MODELS.get(slot, "")


def get_slots(db: Session) -> list[tuple[str, str]]:
    """Configured ``(key, model)`` slots, in round-robin order.

    Falls back to the ``OPENROUTER_API_KEY`` env var when no keys are saved.
    """
    slots: list[tuple[str, str]] = []
    for i in (1, 2):
        key = get_setting(db, f"or_key_{i}", "").strip()
        if key:
            slots.append((key, get_model(db, i)))
    if not slots:
        env_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if env_key:
            slots.append((env_key, os.environ.get("OPENROUTER_MODEL", DEFAULT_MODELS[1])))
    return slots


def slot_status(db: Session) -> dict[int, bool]:
    """Whether each slot has a key saved."""
    return {i: bool(get_setting(db, f"or_key_{i}", "").strip()) for i in (1, 2)}


def get_schedule_model(db: Session) -> str:
    """Smart model for classifying distinct anchors."""
    return get_setting(db, "or_model_schedule", "").strip() or SCHEDULE_DEFAULT_MODEL


def get_schedule_cheap_model(db: Session) -> str:
    """Cheap fallback model, used only for anchors the smart model didn't label."""
    return get_setting(db, "or_model_schedule_cheap", "").strip() or SCHEDULE_CHEAP_MODEL


def get_any_slot(db: Session) -> tuple[str, str] | None:
    """First available ``(key, model)`` — any configured/env key. Used for
    company anchor-type classification, which works with any OpenRouter key."""
    slots = get_slots(db)
    return slots[0] if slots else None


def get_schedule_key(db: Session) -> str:
    """Resolved key for the Date-distribution tab (own key, else a configured one)."""
    key = get_setting(db, "or_key_schedule", "").strip()
    if key:
        return key
    slots = get_slots(db)  # reuse a configured joke/filter key if present
    return slots[0][0] if slots else ""


def get_schedule_slot(db: Session) -> tuple[str, str] | None:
    """``(key, smart_model)`` for the Date-distribution tab, or ``None`` if no key."""
    key = get_schedule_key(db)
    return (key, get_schedule_model(db)) if key else None


def get_schedule_cheap_slot(db: Session) -> tuple[str, str] | None:
    """``(key, cheap_model)`` fallback slot, or ``None`` if no key / same as smart."""
    key = get_schedule_key(db)
    cheap = get_schedule_cheap_model(db)
    if key and cheap and cheap != get_schedule_model(db):
        return key, cheap
    return None
