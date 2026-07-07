"""Company anchor-type classification (single source of truth).

Seven types used across the app (Excel export column + date distribution):

    ND      Naked Domain  — the URL *with protocol* (https://…)
    BD      Brand         — brand/site name, incl. bare domain WITHOUT protocol
    EM      Exact Match   — anchor equals the promoted keyword exactly
    PM      Partial Match — keyword diluted inside a longer phrase / changed form
    G       Generic       — thematic phrase, in-niche, no keyword
    BD+PM   Brand+Partial — brand name AND a partial keyword in one phrase
    NT      No Text       — image/banner link, no anchor text

Determination is deterministic by default (fast, offline) and can be refined by
a connected OpenRouter model using the reference rubric below.
"""
from __future__ import annotations

import re

from .jokes import openrouter_chat

ND, BD, EM, PM, G, BDPM, NT = "ND", "BD", "EM", "PM", "G", "BD+PM", "NT"
TYPES = [ND, BD, EM, PM, G, BDPM, NT]

LABELS = {
    ND: "Naked Domain — голый URL (с протоколом)",
    BD: "Brand — брендовый",
    EM: "Exact Match — точное вхождение",
    PM: "Partial Match — частичное вхождение",
    G: "Generic — общий тематический",
    BDPM: "Brand + Partial Match — гибрид",
    NT: "No Text — без текстового анкора",
}

# Reference guide (for the in-app справочник page and the LLM rubric).
REFERENCE = [
    {"code": ND, "name": "Naked Domain (голый домен)",
     "definition": "Анкором выступает сам URL с протоколом, без текстового оформления. "
                   "Признак ND — наличие https:// (или http://) в анкоре. Не передаёт ключей, "
                   "но выглядит максимально естественно.",
     "examples": ["https://austriawin24.at"]},
    {"code": BD, "name": "Brand (брендовый)",
     "definition": "Анкор — название бренда/сайта в любом написании, с доменной зоной или без неё, "
                   "но БЕЗ протокола. Голый домен как текст (austriawin24.at) — это BD, а не ND.",
     "examples": ["Austriawin24", "Austriawin24.at", "austriawin24.at"]},
    {"code": EM, "name": "Exact Match (точное вхождение)",
     "definition": "Анкор полностью совпадает с продвигаемым ключом — прямое вхождение без добавлений "
                   "и изменений словоформ.",
     "examples": ["online casino", "online casino ausland", "casino en ligne étranger",
                  "online casino paysafecard"]},
    {"code": PM, "name": "Partial Match (частичное вхождение)",
     "definition": "Ключ входит в анкор частично/в разбавленном виде: с доп. словами, в изменённой "
                   "словоформе, внутри более длинной фразы.",
     "examples": ["Online Casinos für Österreicher", "ausländischen Online Casinos in der Schweiz",
                  "modernes Online Casino für Echtgeldspiele", "Top Paysafecard Casinos"]},
    {"code": G, "name": "Generic (общий, тематический)",
     "definition": "Анкор без ключей, но в тематике портала (контекст обязателен). Пустые служебные "
                   "анкоры («click here») формально тоже G, но в работе не ставим — наш G всегда тематический.",
     "examples": ["geprüfte deutsche Spielportale", "Empfohlene Angebote für Österreich",
                  "Top-Auswahl an Anbieter-Websites", "Online-Spielanbieter mit Mobilfunk-Zahlung"]},
    {"code": BDPM, "name": "Brand + Partial Match (гибрид)",
     "definition": "Анкор объединяет название бренда и частичное вхождение ключа в одной фразе. "
                   "Фиксируем именно как BD+PM, а не BD или PM по отдельности.",
     "examples": ["Handy Zahlung auf Gold-Chip.at", "Casino Vergleich von Austriawin24"]},
    {"code": NT, "name": "No Text (без текстового анкора)",
     "definition": "Ссылка с изображения (баннер, логотип, инфографика) — текстового анкора нет; "
                   "поисковик использует alt-текст. В отчётности помечаем как NT.",
     "examples": ["ссылка с баннера", "ссылка с логотипа бренда в статье"]},
]

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def squash(s: str) -> str:
    """Lowercase, keep only alphanumerics (collapse spaces/punctuation)."""
    return re.sub(r"[^\w]", "", (s or "").lower(), flags=re.UNICODE)


def looks_naked_url(s: str) -> bool:
    return bool(re.match(r"^\s*https?://", (s or ""), re.I))


def looks_bare_domain(s: str) -> bool:
    v = (s or "").strip().lower()
    if not v or " " in v:
        return False
    return bool(re.match(r"^([a-z0-9-]+\.)+[a-z]{2,}/?$", v))


def looks_urlish(s: str) -> bool:
    """Naked URL (with protocol) or a bare domain (no protocol)."""
    return looks_naked_url(s) or looks_bare_domain(s)


def _tokens(s: str) -> set[str]:
    return set(_WORD_RE.findall((s or "").lower()))


def classify_one(anchor: str, brand: str = "", keywords: frozenset[str] | set[str] = frozenset()) -> str:
    """Deterministic best-guess type for one anchor.

    ``keywords`` is a set of the project's lowercased keywords (used to tell
    EM/PM/G apart). Without it, EM/PM detection is limited (falls back to G).
    """
    a = (anchor or "").strip()
    if not a:
        return NT
    if looks_naked_url(a):
        return ND
    if looks_bare_domain(a):
        return BD
    sq_a, sq_brand = squash(a), squash(brand)
    has_brand = bool(sq_brand) and len(sq_brand) >= 3 and sq_brand in sq_a
    low = a.lower()
    brand_tokens = _tokens(brand)
    kw_tokens: set[str] = set()
    for k in keywords:
        kw_tokens |= _tokens(k)
    a_tokens = _tokens(a)
    overlap = bool((kw_tokens - brand_tokens) & a_tokens)  # keyword material beyond the brand
    exact = low in {k.lower() for k in keywords}

    if sq_brand and sq_a == sq_brand:
        return BD                     # exactly the brand name/domain
    if has_brand:
        return BDPM if overlap else BD  # brand + keyword phrase vs brand variant
    if exact:
        return EM
    if overlap:
        return PM
    return G


def llm_classify(anchors: list[str], key: str, model: str) -> dict[str, str]:
    """Refine anchor types with an OpenRouter model using the reference rubric."""
    result: dict[str, str] = {}
    if not anchors:
        return result
    rubric = "\n".join(f"{r['code']} = {r['name']}: {r['definition']}" for r in REFERENCE)
    valid = {t.upper(): t for t in TYPES}
    chunk = 40
    for i in range(0, len(anchors), chunk):
        part = anchors[i:i + chunk]
        numbered = "\n".join(f"{j + 1}. {a}" for j, a in enumerate(part))
        prompt = (
            "Ты классифицируешь анкорные тексты по внутреннему справочнику компании.\n"
            "Типы:\n" + rubric + "\n\n"
            "Для каждого анкора верни строку вида «номер=КОД» (КОД — один из: "
            + ", ".join(TYPES) + "). Без пояснений.\n\n" + numbered
        )
        text = openrouter_chat(key, model, prompt, max_tokens=700, timeout=20)
        if not text:
            continue
        for m in re.finditer(r"(\d+)\s*=\s*(BD\+PM|ND|BD|EM|PM|G|NT)", text, re.I):
            j = int(m.group(1)) - 1
            code = valid.get(m.group(2).upper())
            if 0 <= j < len(part) and code:
                result[part[j]] = code
    return result


def build_type_map(anchors, *, brand: str = "", keywords=(), slot: tuple[str, str] | None = None) -> dict[str, str]:
    """Map every distinct anchor to a type. Deterministic first; when a model
    ``slot`` is given, text anchors (non ND/NT) are refined per the rubric."""
    kws = frozenset(k.lower() for k in keywords)
    result = {a: classify_one(a, brand, kws) for a in set(anchors)}
    if slot:
        text_anchors = [a for a, t in result.items() if t not in (ND, NT)]
        for a, code in llm_classify(sorted(text_anchors), slot[0], slot[1]).items():
            result[a] = code
    return result
