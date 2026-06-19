"""SQLAlchemy ORM models.

The data model mirrors the entities in the spec (§3):

* :class:`Strategy`       - named anchor profile (anchorless % + ordered roles).
* :class:`AnchorlessFormat` - a way to render an anchorless link (bare url, markdown...).
* :class:`InternalPageSuffix` - dictionary ``page type + language -> anchor suffix`` (§3.6).
* :class:`Project`        - a domain to process, with its frequency keywords and
  internal-page path mapping.
* :class:`Keyword`        - a single ``keyword | frequency`` row of a project's
  frequency table (§3.2).
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
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
    # When True this is a campaign-type preset (e.g. "крауд+сабмиты" = 100% anchorless).
    is_builtin = Column(Boolean, default=False)


class AnchorlessFormat(Base):
    """A rendering template for an anchorless link (§3.5).

    ``template`` may contain ``{url}`` and ``{domain}`` placeholders.
    ``sub_weight`` is expressed as a percentage of the *total* volume.
    """

    __tablename__ = "anchorless_formats"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    template = Column(String, nullable=False, default="{url}")
    sub_weight = Column(Float, nullable=False, default=0.0)
    position = Column(Integer, nullable=False, default=0)


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

    internal_language = Column(String, nullable=False, default="en")
    # JSON mapping page_type -> url path, e.g. {"app": "/app/", "login": "/login/"}.
    internal_pages_json = Column(Text, nullable=False, default="{}")
    # Optional manual redistribution of missing roles (§4.2), JSON:
    # {"добавочный 2": {"основной 1": 100}}  -> freed % goes 100% to "основной 1".
    redistribution_json = Column(Text, nullable=False, default="{}")

    strategy = relationship("Strategy")
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
