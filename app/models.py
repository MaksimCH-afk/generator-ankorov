"""SQLAlchemy ORM models.

The data model mirrors the entities in the spec (§3):

* :class:`Strategy`       - named anchor profile (anchorless % + ordered roles).
* :class:`AnchorlessProfile` - a saved profile of anchorless link formats.
* :class:`InternalPageSuffix` - dictionary ``page type + language -> anchor suffix`` (§3.6).
* :class:`Project`        - a domain to process, with its frequency keywords and
  internal-page path mapping.
* :class:`Keyword`        - a single ``keyword | frequency`` row of a project's
  frequency table (§3.2).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base

# Supported localisation languages for internal-page anchor suffixes (§3.6 / Q10).
SUFFIX_LANGUAGES = ["en", "de", "pl", "tr", "pt-br"]

# SEO specialists offered in the export dropdown (default = first).
SEO_SPECIALISTS = ["Miles Nashwood"]

# Preset article languages offered as a dropdown for projects (English names).
# Empty string is used as the special "do not include in export" value.
ARTICLE_LANGUAGES = [
    "English",
    "German",
    "French",
    "Spanish",
    "Italian",
    "Portuguese",
    "Portuguese (Brazil)",
    "Dutch",
    "Polish",
    "Czech",
    "Slovak",
    "Hungarian",
    "Romanian",
    "Greek",
    "Turkish",
    "Danish",
    "Swedish",
    "Norwegian",
    "Finnish",
    "Bulgarian",
    "Croatian",
    "Slovenian",
    "Serbian",
    "Ukrainian",
    "Russian",
    "Japanese",
    "Korean",
    "Chinese",
    "Arabic",
    "Hindi",
]


class Strategy(Base):
    """A named anchor profile.

    ``roles`` is stored as JSON text: an ordered list of
    ``{"name": str, "percent": float}``. The anchorless weight is stored
    separately in :attr:`anchorless_percent`. The sum of anchorless + all role
    percents must equal 100 (validated on save, §9).
    """

    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    anchorless_percent = Column(Float, nullable=False, default=0.0)
    roles_json = Column(Text, nullable=False, default="[]")
    # Which anchorless profile this strategy uses (how the anchorless share looks).
    anchorless_profile_id = Column(Integer, ForeignKey("anchorless_profiles.id"), nullable=True)
    # When True this is a campaign-type preset (e.g. "крауд+сабмиты" = 100% anchorless).
    is_builtin = Column(Boolean, default=False)

    anchorless_profile = relationship("AnchorlessProfile")


class AnchorlessProfile(Base):
    """A saved anchorless profile — like a strategy, but for anchorless link
    formats. ``items_json`` is an ordered list of
    ``{"name": str, "template": str, "percent": float}``; percents are relative
    weights used to split the anchorless share across the formats.
    """

    __tablename__ = "anchorless_profiles"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    items_json = Column(Text, nullable=False, default="[]")
    is_builtin = Column(Boolean, default=False)


class InternalPageSuffix(Base):
    """Dictionary entry ``page type + language -> anchor suffix`` (§3.6)."""

    __tablename__ = "internal_page_suffixes"
    __table_args__ = (UniqueConstraint("page_type", "language", name="uq_pagetype_lang"),)

    id = Column(Integer, primary_key=True)
    page_type = Column(String, nullable=False)
    language = Column(String, nullable=False)
    suffix = Column(String, nullable=False)


class Project(Base):
    """A domain to process (§3.1)."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    url = Column(String, nullable=False)
    language = Column(String, nullable=False, default="English")  # article language
    brand = Column(String, nullable=False, default="")

    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    volume = Column(Integer, nullable=False, default=100)        # "прогоны" volume
    crowd_volume = Column(Integer, nullable=False, default=0)    # "крауд+сабмиты" volume
    # Anchorless profile (how the anchorless share is split across formats).
    anchorless_profile_id = Column(Integer, ForeignKey("anchorless_profiles.id"), nullable=True)

    internal_language = Column(String, nullable=False, default="en")
    # JSON mapping page_type -> url path, e.g. {"app": "/app/", "login": "/login/"}.
    internal_pages_json = Column(Text, nullable=False, default="{}")
    # Optional manual redistribution of missing roles (§4.2), JSON:
    # {"добавочный 2": {"основной 1": 100}}  -> freed % goes 100% to "основной 1".
    redistribution_json = Column(Text, nullable=False, default="{}")

    strategy = relationship("Strategy")
    anchorless_profile = relationship("AnchorlessProfile")
    keywords = relationship(
        "Keyword",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Keyword.position",
    )


class Keyword(Base):
    """A single ``keyword | frequency`` row of a project's frequency table."""

    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    keyword = Column(String, nullable=False)
    frequency = Column(Float, nullable=False, default=0.0)
    position = Column(Integer, nullable=False, default=0)  # original file order (tie-break, §4.4)

    project = relationship("Project", back_populates="keywords")


class Log(Base):
    """A detailed application event log entry (uploads, edits, generation, errors)."""

    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    level = Column(String, nullable=False, default="INFO")     # INFO / WARNING / ERROR
    category = Column(String, nullable=False, default="general")  # upload / project / generate / ...
    message = Column(String, nullable=False, default="")
    details = Column(Text, nullable=False, default="")


class History(Base):
    """A record of one generated project (what / how / when), saved on generation."""

    __tablename__ = "history"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    project_url = Column(String, nullable=False, default="")
    brand = Column(String, nullable=False, default="")
    language = Column(String, nullable=False, default="")
    strategy_name = Column(String, nullable=False, default="")
    volume = Column(Integer, nullable=False, default=0)
    crowd_volume = Column(Integer, nullable=False, default=0)
    export_format = Column(String, nullable=False, default="")  # zip / separate
    rows_total = Column(Integer, nullable=False, default=0)
    sheets_json = Column(Text, nullable=False, default="{}")    # {sheet: {rows, links}}


class AppSetting(Base):
    """Simple key/value store (e.g. OpenRouter keys for the joke widget)."""

    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False, default="")


class IgnoreAnchor(Base):
    """A stop-phrase: keywords semantically similar to it are excluded from the
    strategy when smart anchor filtering is enabled (e.g. "login", "free spins")."""

    __tablename__ = "ignore_anchors"

    id = Column(Integer, primary_key=True)
    phrase = Column(String, unique=True, nullable=False)
