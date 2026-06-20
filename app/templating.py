"""Shared Jinja2 templates instance (used by all routers)."""
from __future__ import annotations

import os

from fastapi.templating import Jinja2Templates

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
