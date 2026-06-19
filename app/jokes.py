"""SEO joke provider for the little widget in the UI.

Tries an OpenRouter free model; on any failure (no key, no network, rate limit,
bad response) falls back to a built-in list so the widget always shows
something. The API key is read from the ``OPENROUTER_API_KEY`` environment
variable (set it in a local ``.env`` file — see ``.env.example``). The key is
never stored in the repository.
"""
from __future__ import annotations

import json
import os
import random
import urllib.request

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

FALLBACK_JOKES = [
    "SEO-специалист заходит в бар, бары, паб, пивную, питейное заведение, выпивку рядом со мной…",
    "— Сколько SEO-шников нужно, чтобы вкрутить лампочку? — Зависит от того, по какому запросу её ищут.",
    "SEO-специалист не опаздывает — он просто ждёт переиндексации.",
    "Жена спросила SEO-шника, любит ли он её. Он ответил: «Ты в топ-3 моего сердца, но давай поработаем над позицией».",
    "Лучшее место, чтобы спрятать труп, — вторая страница выдачи Google.",
    "SEO — это как свидание вслепую с Google: ты стараешься, а он всё равно меняет алгоритм.",
    "— Как дела? — Жду апдейт ядра, потом скажу.",
    "SEO-специалист сажает дерево и сразу проверяет, проиндексировалось ли оно.",
    "Дзен SEO-шника: трафик приходит и уходит, а ниндекс вечен.",
    "У SEO-специалиста две беды: фильтры Google и заказчик, который «уже всё сам настроил».",
    "SEO-специалист расстался с девушкой: у неё был слишком высокий показатель отказов.",
    "— Папа, расскажи сказку. — Жили-были ключевые слова, и все они хотели в топ…",
    "Главное правило SEO: если ничего не помогает — добавь ещё контента и подожди три месяца.",
    "SEO-шник не верит в удачу. Он верит в анкор-лист и крауд-ссылки.",
    "Google обновил алгоритм. SEO-специалисты обновили резюме.",
]


def get_joke() -> str:
    """Return a short SEO joke (LLM if available, otherwise a local one)."""
    joke = _from_openrouter()
    return joke or random.choice(FALLBACK_JOKES)


def _from_openrouter() -> str | None:
    if not OPENROUTER_API_KEY:
        return None
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "Ты генерируешь короткие смешные шутки про SEO-специалистов на русском языке. Только одна шутка, 1–2 предложения, без вступлений и пояснений."},
            {"role": "user", "content": "Расскажи новую короткую шутку про SEO-специалиста."},
        ],
        "max_tokens": 120,
        "temperature": 1.0,
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:9999",
            "X-Title": "HubNero Anchor Generator",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        return text.strip('"').strip() or None
    except Exception:
        return None
