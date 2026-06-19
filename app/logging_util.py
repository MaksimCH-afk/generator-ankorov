"""Tiny DB-backed event logger used across the app (powers the Logs page)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Log


def log_event(db: Session, level: str, category: str, message: str, details: str = "") -> None:
    """Persist a log entry. Never raises — logging must not break the request."""
    try:
        db.add(Log(level=level, category=category, message=message, details=details))
        db.commit()
    except Exception:  # pragma: no cover - logging must be best-effort
        db.rollback()
