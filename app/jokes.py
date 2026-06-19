"""SEO joke provider for the topbar widget.

Variety strategy:
* LLM batch cache (F): request ~12 jokes at once from OpenRouter, queue them,
  serve one at a time; refill when empty. Round-robin across the configured
  key/model slots to dodge a single model's timeouts/limits.
* No-repeat memory (C): remember the last N served jokes, never repeat them.
* Shuffled deck (A): the local fallback list is dealt without replacement,
  reshuffled when exhausted.
* Large fallback pool (B): ~60 built-in jokes so even offline it stays fresh.

All network calls are best-effort; on any failure we serve a fallback joke.
"""
from __future__ import annotations

import json
import random
import urllib.request
from collections import deque

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

FALLBACK_JOKES = [
    "Клиент: «А гарантии есть?» SEO-специалист молча показывает на логотип Google.",
    "Google обновил алгоритм. SEO-специалисты обновили резюме.",
    "SEO-специалист сажает дерево и сразу проверяет, проиндексировалось ли оно.",
    "SEO-шник не верит в удачу. Он верит в анкор-лист и крауд-ссылки.",
    "Главное правило SEO: если ничего не помогает — добавь ещё контента и подожди три месяца.",
    "SEO-специалист переименовал ребёнка в H1 — слишком уж он был важный.",
    "— Сколько SEO-шников нужно, чтобы вкрутить лампочку? — Зависит, по какому запросу её ищут.",
    "SEO-специалист не опаздывает — он просто ждёт переиндексации.",
    "Лучшее место спрятать труп — вторая страница выдачи Google.",
    "SEO — это как свидание вслепую с Google: ты стараешься, а он всё равно меняет алгоритм.",
    "— Как дела? — Жду апдейт ядра, потом скажу.",
    "Дзен SEO-шника: трафик приходит и уходит, а ниндекс вечен.",
    "У SEO-специалиста две беды: фильтры Google и заказчик, который «уже всё сам настроил».",
    "SEO-специалист расстался с девушкой: у неё был слишком высокий показатель отказов.",
    "— Папа, расскажи сказку. — Жили-были ключевые слова, и все они хотели в топ…",
    "SEO-специалист в ресторане: «Мне, пожалуйста, что-нибудь из топа меню».",
    "Почему SEO-шник плохо спит? Боится, что ночью прилетит ручная санкция.",
    "SEO-шник назвал кота Title, а собаку — Description. Оба не уникальные.",
    "— Дорогой, ты меня любишь? — Конечно, ты у меня в featured snippet.",
    "SEO-специалист не верит обещаниям «топ за неделю» — он сам их раздаёт клиентам.",
    "Оптимизатор оптимизировал-оптимизировал, да недооптимизировал краулинговый бюджет.",
    "Самый страшный сон SEO-шника: «Ваш сайт переехал на JS без SSR».",
    "SEO — единственная профессия, где «ссылки с заборов» это работа, а не вандализм.",
    "У SEO-специалиста на двери табличка: «Не беспокоить, идёт линкбилдинг».",
    "SEO-шник считает овец: «Овца №1, овца №2… а у этой какой anchor text?»",
    "Робот Googlebot и SEO-специалист заходят в бар. Бар не проиндексирован.",
    "Метатег description в резюме SEO-шника: «Открыт к релевантным предложениям».",
    "SEO-специалист на свадьбе кричит: «Горько!» — и проверяет, выросла ли вовлечённость.",
    "Жена: «Ты меня вообще слушаешь?» SEO-шник: «Секунду, дочитаю гайдлайны Google».",
    "Лучший комплимент SEO-шнику: «У тебя сегодня отличный CTR».",
    "SEO-специалист не стареет — он просто наращивает возрастную массу домена.",
    "Тамада хороший и конкурсы интересные, но мета-теги не заполнены.",
    "SEO-шник вместо «доброе утро» говорит «доброе ядро».",
    "Как испугать SEO-специалиста? Шепнуть ему на ухо: «noindex, nofollow».",
    "SEO-специалисту подарили цветы — он сразу проверил их на дубли.",
    "— Чем занимаешься? — Жду, пока Google полюбит меня обратно.",
    "SEO-шник пришёл к психологу: «Меня никто не индексирует».",
    "Девиз SEO-отдела: семантику собрали — считай, полдела сделали, осталась вторая половина… года.",
    "SEO-специалист не говорит «никогда». Он говорит «вне индекса».",
    "Худшее оскорбление для SEO-шника: «у тебя тонкий контент».",
    "SEO — это искусство объяснять, почему трафик упал не из-за тебя.",
    "У хорошего SEO-шника даже список покупок имеет правильную вложенность заголовков.",
    "SEO-специалист рыбачит: важна не рыба, а сколько внешних ссылок на этот пруд.",
    "Google: «Мы ценим качественный контент». SEO-шники: нервно смотрят на 200 статей по 300 слов.",
    "SEO-специалист медитирует: вдох — апдейт, выдох — откат позиций.",
    "— Какой у тебя план на жизнь? — Сначала в топ-10, потом разберёмся.",
    "SEO-шник не ходит налево — у него и так слишком много исходящих ссылок.",
    "Новый год для SEO начинается с core update, а не с курантов.",
    "SEO-специалист объясняет ребёнку светофор: «Зелёный — рост, красный — фильтр, жёлтый — песочница».",
    "Резюме SEO-шника проиндексировалось быстрее, чем его последний проект.",
    "SEO-специалист гадает на ромашке: «в топе — не в топе — в топе — апдейт».",
    "Любимый праздник SEO-шника — день, когда конкурент попал под фильтр.",
    "SEO — это когда ты три месяца ждёшь, а потом всё равно «нужно ещё подождать».",
    "SEO-специалист не верит в магию. Он верит в перелинковку.",
    "Самая длинная единица времени — «Google скоро пересчитает позиции».",
    "SEO-шник назвал Wi-Fi сеть «Free Backlinks» — соседи кликают, он считает трафик.",
    "Поссорились два SEO-шника: не сошлись в плотности ключей.",
    "SEO-специалист на приёме у врача: «Доктор, у меня выпадение… из индекса».",
    "Идеальное свидание SEO-шника: ужин, прогулка и обсуждение скорости загрузки сайта.",
    "SEO — это вера в то, что завтрашний апдейт будет к тебе добрее вчерашнего.",
]

_queue: deque[str] = deque()
_recent: deque[str] = deque(maxlen=30)
_deck: list[str] = []
_rr = {"i": 0}


def openrouter_chat(key: str, model: str, prompt: str, max_tokens: int = 400, timeout: int = 12) -> str | None:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Ты генерируешь смешные короткие шутки про SEO-специалистов на русском. Без вступлений и пояснений."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 1.1,
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:9999",
            "X-Title": "HubNero Anchor Generator",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip() or None
    except Exception:
        return None


def _clean(line: str) -> str:
    line = line.strip().lstrip("0123456789.)-—•* ").strip()
    return line.strip('"').strip("«»").strip()


def batch_jokes(key: str, model: str, n: int = 12) -> list[str]:
    text = openrouter_chat(
        key, model,
        f"Сгенерируй {n} разных коротких шуток про SEO-специалистов на русском. "
        "Каждая шутка с новой строки, без нумерации и кавычек.",
        max_tokens=600,
    )
    if not text:
        return []
    out = []
    for raw in text.splitlines():
        j = _clean(raw)
        if 12 <= len(j) <= 240:
            out.append(j)
    return out


def ping(key: str, model: str) -> bool:
    """Lightweight check that a key/model works."""
    return bool(openrouter_chat(key, model, "Скажи одно слово: ок.", max_tokens=8, timeout=10))


def _fill_queue(slots: list[tuple[str, str]]) -> None:
    if _queue or not slots:
        return
    for _ in range(len(slots)):
        key, model = slots[_rr["i"] % len(slots)]
        _rr["i"] += 1
        for j in batch_jokes(key, model):
            if j not in _recent and j not in _queue:
                _queue.append(j)
        if _queue:
            return


def _from_deck() -> str:
    global _deck
    if not _deck:
        _deck = FALLBACK_JOKES[:]
        random.shuffle(_deck)
    # deal without replacement, skipping recently shown when possible
    for _ in range(len(_deck)):
        j = _deck.pop()
        if not _deck:
            _deck = FALLBACK_JOKES[:]
            random.shuffle(_deck)
        if j not in _recent:
            return j
    return random.choice(FALLBACK_JOKES)


def get_joke(slots: list[tuple[str, str]] | None = None) -> str:
    slots = slots or []
    joke = None
    if not _queue:
        _fill_queue(slots)
    while _queue:
        cand = _queue.popleft()
        if cand not in _recent:
            joke = cand
            break
    if not joke:
        joke = _from_deck()
    _recent.append(joke)
    return joke
