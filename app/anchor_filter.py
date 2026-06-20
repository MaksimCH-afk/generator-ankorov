"""Smart anchor filter.

Given a list of keywords and a list of stop-phrases, decides which keywords
should be excluded from the strategy *by meaning* (not just substring). Uses the
configured OpenRouter key/model slots, splitting the keywords across the slots so
two models work in parallel for speed. Falls back to substring matching when no
keys are configured or a request fails.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from .jokes import openrouter_chat

_CHUNK = 40  # keywords per LLM request


def _substring_removed(keywords: list[str], phrases: list[str]) -> set[str]:
    pl = [p.lower().strip() for p in phrases if p.strip()]
    removed = set()
    for kw in keywords:
        low = kw.lower()
        if any(p in low for p in pl):
            removed.add(kw)
    return removed


def _classify(keywords: list[str], phrases: list[str], key: str, model: str) -> set[str]:
    """LLM semantic classification for one slot's keywords (chunked)."""
    removed: set[str] = set()
    for i in range(0, len(keywords), _CHUNK):
        chunk = keywords[i:i + _CHUNK]
        numbered = "\n".join(f"{j + 1}. {k}" for j, k in enumerate(chunk))
        prompt = (
            "Стоп-темы: " + "; ".join(phrases) + ".\n"
            "Список ключей:\n" + numbered + "\n\n"
            "Верни номера тех ключей, которые ПО СМЫСЛУ относятся к любой из стоп-тем "
            "(даже если слова другие/синонимы/на другом языке). "
            "Только номера через запятую, без пояснений. Если подходящих нет — напиши 0."
        )
        text = openrouter_chat(key, model, prompt, max_tokens=200, timeout=20)
        if text is None:
            removed |= _substring_removed(chunk, phrases)  # fallback for this chunk
            continue
        for tok in re.findall(r"\d+", text):
            idx = int(tok) - 1
            if 0 <= idx < len(chunk):
                removed.add(chunk[idx])
    return removed


def filter_keywords(keywords: list[str], phrases: list[str],
                    slots: list[tuple[str, str]]) -> tuple[list[str], set[str], str]:
    """Return ``(kept, removed, mode)``.

    ``mode`` is "semantic" (LLM) or "substring" (fallback). Keywords are
    de-duplicated preserving order.
    """
    keywords = list(dict.fromkeys(keywords))
    phrases = [p.strip() for p in phrases if p.strip()]
    if not phrases or not keywords:
        return keywords, set(), "none"

    if not slots:
        removed = _substring_removed(keywords, phrases)
        return [k for k in keywords if k not in removed], removed, "substring"

    n = len(slots)
    parts = [keywords[i::n] for i in range(n)]  # round-robin split across slots
    removed: set[str] = set()
    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_classify, parts[i], phrases, slots[i][0], slots[i][1]) for i in range(n)]
        for fut in futures:
            try:
                removed |= fut.result()
            except Exception:
                pass
    kept = [k for k in keywords if k not in removed]
    return kept, removed, "semantic"
