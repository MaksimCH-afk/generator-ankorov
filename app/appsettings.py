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
