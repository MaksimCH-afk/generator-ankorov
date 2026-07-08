"""Tiny in-memory handoff store: per-project generated files kept briefly so the
Date-distribution tab can consume them directly (skipping download + re-upload).

Keyed by the generation token. Bounded to the most recent runs. In-memory only
(cleared on restart) — this is a convenience bridge, not persistent storage.
"""
from __future__ import annotations

from collections import OrderedDict

_RUNS: "OrderedDict[str, dict[str, bytes]]" = OrderedDict()
_LIMIT = 20


def save_run(token: str, files: dict[str, bytes]) -> None:
    _RUNS[token] = dict(files)
    _RUNS.move_to_end(token)
    while len(_RUNS) > _LIMIT:
        _RUNS.popitem(last=False)


def get_run(token: str) -> dict[str, bytes] | None:
    return _RUNS.get(token)
