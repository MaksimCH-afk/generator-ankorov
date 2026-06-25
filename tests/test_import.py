"""Tests for the smart project-import parser and anchorless profiles."""
from app.parsing import normalize_domain, parse_project_sheet, parse_project_sheet_multi
from app.service import profile_to_formats
from app import generator as gen


def test_normalize_domain_http_to_https():
    assert normalize_domain("http://pandidocasinos.at/") == "https://pandidocasinos.at/"
    assert normalize_domain("bet-alice-at.at") == "https://bet-alice-at.at/"
    assert normalize_domain("https://vikingluck-casino.at/") == "https://vikingluck-casino.at/"


def test_normalize_domain_malformed_schemes():
    canonical = "https://silverplaycasino-austria.com/"
    for raw in [
        "silverplaycasino-austria.com/",
        "https:/silverplaycasino-austria.com/",
        "http:/silverplaycasino-austria.com/",
        "http:/silverplaycasino-austria.com",
        "silverplaycasino-austria.com",
        "http://silverplaycasino-austria.com/",
        "http/silverplaycasino-austria.com/",
        "https://www.silverplaycasino-austria.com",
    ]:
        assert normalize_domain(raw) == canonical, raw


def test_multiple_domains_one_keyword_set():
    rows = [
        ["Keyword", "Volume", "Перевод", "Difficulty", ""],
        ["silverplay casino", "150", "", "36", "silverplaycasinos.at"],
        ["silverplay", "150", "", "41", "silverplay-casino.co.at"],
        ["silver play casino", "60", "", "3", "silverplaycasino-austria.com"],
    ]
    domains, pairs = parse_project_sheet_multi(rows)
    assert domains == [
        "https://silverplaycasinos.at/",
        "https://silverplay-casino.co.at/",
        "https://silverplaycasino-austria.com/",
    ]
    assert [p[0] for p in pairs] == ["silverplay casino", "silverplay", "silver play casino"]
    # The single-domain helper still returns the first.
    first, _ = parse_project_sheet(rows)
    assert first == "https://silverplaycasinos.at/"


def test_domain_in_header_cell():
    rows = [
        ["Keyword", "Volume", "Перевод", "bet-alice-at.at"],
        ["betalice", "450", "Беталис", ""],
        ["betalice casino", "200", "казино", ""],
    ]
    domain, pairs = parse_project_sheet(rows)
    assert domain == "https://bet-alice-at.at/"
    assert pairs == [("betalice", 450.0), ("betalice casino", 200.0)]


def test_domain_in_column_and_shifted_header():
    rows = [
        ["https://viperwin-casino.at/", "Keyword", "Volume", "Перевод"],
        ["", "viperwin", "60", "viperwin"],
        ["", "viperwin casino", "30", "казино"],
    ]
    domain, pairs = parse_project_sheet(rows)
    assert domain == "https://viperwin-casino.at/"
    assert pairs == [("viperwin", 60.0), ("viperwin casino", 30.0)]


def test_domain_repeated_in_translation_column():
    rows = [
        ["Keyword", "Volume", "Перевод"],
        ["viking luck casino", "50", "https://vikingluck-casino.at/"],
        ["vikingluck", "20", "https://vikingluck-casino.at/"],
    ]
    domain, pairs = parse_project_sheet(rows)
    assert domain == "https://vikingluck-casino.at/"
    assert [p[0] for p in pairs] == ["viking luck casino", "vikingluck"]


def test_summary_sheet_skipped():
    rows = [["Сводная"], ["betalice"], ["pandido"]]
    domain, pairs = parse_project_sheet(rows)
    assert pairs == []  # no keyword header -> skipped


def test_empty_sheet_skipped():
    rows = [["Keyword", "Volume", "Перевод"]]  # header only
    domain, pairs = parse_project_sheet(rows)
    assert pairs == []


def test_kd_column_ignored():
    rows = [
        ["Keyword", "KD", "Volume"],
        ["betalice", "45", "450"],
    ]
    domain, pairs = parse_project_sheet(rows)
    assert pairs == [("betalice", 450.0)]  # volume read from the right column, KD ignored


def test_profile_split_relative_weights():
    profile_items = [
        {"name": "Голый домен", "template": "{domain}", "percent": 60},
        {"name": "Голый URL", "template": "{url}", "percent": 15},
    ]

    class P:  # minimal stand-in for AnchorlessProfile
        items_json = __import__("json").dumps(profile_items)

    formats = profile_to_formats(P())
    rows = gen.split_anchorless(100, formats, "https://betalice.com/")
    counts = {text: n for text, n in rows}
    # 60:15 of 100 -> 80:20, last absorbs remainder
    assert sum(counts.values()) == 100
    assert counts["betalice.com"] == 80
    assert counts["https://betalice.com/"] == 20
