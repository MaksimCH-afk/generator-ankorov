"""Smart anchor filter — substring fallback (deterministic, no network)."""
import app.anchor_filter as af
from app.anchor_filter import filter_keywords


def test_substring_fallback_no_slots():
    keywords = ["betalice", "betalice login", "free spins betalice", "betalice casino"]
    phrases = ["login", "free spins"]
    kept, removed, mode = filter_keywords(keywords, phrases, slots=[])
    assert mode == "substring"
    assert removed == {"betalice login", "free spins betalice"}
    assert kept == ["betalice", "betalice casino"]


def test_no_phrases_keeps_all():
    kept, removed, mode = filter_keywords(["a", "b"], [], slots=[])
    assert removed == set()
    assert kept == ["a", "b"]
    assert mode == "none"


def test_dedup_preserves_order():
    kept, removed, mode = filter_keywords(["a", "a", "b"], ["x"], slots=[])
    assert kept == ["a", "b"]


def _fake_chat_factory(flag_words):
    """Mock openrouter_chat: flag numbered keywords whose text contains any word."""
    import re

    def fake_chat(key, model, prompt, max_tokens=200, timeout=20):
        hits = []
        for line in prompt.splitlines():
            m = re.match(r"^(\d+)\.\s*(.+)$", line)
            if m and any(w in m.group(2).lower() for w in flag_words):
                hits.append(m.group(1))
        return ",".join(hits) if hits else "0"

    return fake_chat


def test_semantic_uses_both_slots_and_meaning(monkeypatch):
    seen = set()
    base = _fake_chat_factory(["бонус", "casino", "spins"])

    def chat(key, model, prompt, max_tokens=200, timeout=20):
        seen.add(model)
        return base(key, model, prompt, max_tokens, timeout)

    monkeypatch.setattr(af, "openrouter_chat", chat)
    keywords = ["обзор", "приветственный бонус", "casino x", "погода", "free spins тут"]
    phrases = ["no deposit bonus", "free spins", "casino"]
    kept, removed, mode = filter_keywords(keywords, phrases, [("k1", "m1"), ("k2", "m2")])
    assert mode == "semantic"
    assert seen == {"m1", "m2"}  # keywords split across both slots
    # "приветственный бонус" matches by meaning, not substring
    assert removed == {"приветственный бонус", "casino x", "free spins тут"}
    assert kept == ["обзор", "погода"]


def test_semantic_falls_back_per_chunk_on_failure(monkeypatch):
    def chat(key, model, prompt, max_tokens=200, timeout=20):
        return None  # simulate timeout / 429 / network error

    monkeypatch.setattr(af, "openrouter_chat", chat)
    keywords = ["alpha login", "beta clean", "gamma free spins"]
    phrases = ["login", "free spins"]
    kept, removed, mode = filter_keywords(keywords, phrases, [("k1", "m1"), ("k2", "m2")])
    assert mode == "semantic"
    assert removed == {"alpha login", "gamma free spins"}  # substring fallback still works
    assert kept == ["beta clean"]
