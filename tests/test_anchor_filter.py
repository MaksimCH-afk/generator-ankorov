"""Smart anchor filter — substring fallback (deterministic, no network)."""
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
