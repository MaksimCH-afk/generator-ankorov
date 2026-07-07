"""FastAPI application: wires routers, static files, startup seeding."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .routers import (
    anchors,
    generation,
    history,
    logs,
    profiles,
    projects,
    schedule,
    strategies,
    suffixes,
)
from .seed import seed

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="HubNero · Генератор анкоров")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

for module in (projects, generation, schedule, strategies, profiles, suffixes, history, logs, anchors):
    app.include_router(module.router)


@app.on_event("startup")
def _startup() -> None:
    seed()


@app.get("/favicon.ico")
def favicon():
    return RedirectResponse("/static/favicon.svg", status_code=307)


@app.get("/health")
def health():
    return {"status": "ok"}
