"""Unit tests for the pure generation engine (§4, §9)."""
from app import generator as gen


def make_strategy_safe() -> gen.Strategy:
    # "Безопасная": 75 / 13 / 5 / 4 / 3 = 100%
    return gen.Strategy(
        name="Безопасная",
        anchorless_percent=75,
        roles=[
            gen.Role("основной 1", 13),
            gen.Role("основной 2", 5),
            gen.Role("добавочный 1", 4),
            gen.Role("добавочный 2", 3),
        ],
    )


def make_project(keywords):
    return gen.ProjectInput(
        url="https://cowboyspin-ceska.org/",
        article_language="Czech",
        brand="cowboy spin",
        keywords=[gen.KeywordInput(k, f, i) for i, (k, f) in enumerate(keywords)],
    )


def test_role_assignment_sorted_by_frequency():
    project = make_project([("b", 10), ("a", 50), ("c", 30)])
    strat = make_strategy_safe()
    mapping = gen.assign_roles(project.keywords, strat.roles)
    assert mapping["основной 1"].keyword == "a"
    assert mapping["основной 2"].keyword == "c"
    assert mapping["добавочный 1"].keyword == "b"
    assert mapping["добавочный 2"] is None  # only 3 keywords, 4 roles


def test_tie_break_by_position():
    project = make_project([("first", 10), ("second", 10)])
    mapping = gen.assign_roles(project.keywords, make_strategy_safe().roles)
    assert mapping["основной 1"].keyword == "first"
    assert mapping["основной 2"].keyword == "second"


def test_sum_equals_volume():
    """Sum of all link counts must always equal the volume (§9)."""
    project = make_project([("k1", 100), ("k2", 80), ("k3", 60), ("k4", 40)])
    rows = gen.generate_profile_rows(project, make_strategy_safe(), 200, [])
    assert sum(r.link_qty for r in rows) == 200


def test_anchorless_absorbs_remainder():
    project = make_project([("k1", 100), ("k2", 80), ("k3", 60), ("k4", 40)])
    rows = gen.generate_profile_rows(project, make_strategy_safe(), 200, [])
    # volume 200: roles = round(.13*200)=26, .05->10, .04->8, .03->6 -> 50 anchors
    anchor_rows = [r for r in rows if r.anchor != project.url]
    assert sum(r.link_qty for r in anchor_rows) == 50
    anchorless = [r for r in rows if r.anchor == project.url]
    assert anchorless[0].link_qty == 150


def test_missing_role_goes_to_anchorless():
    """Only 3 keywords for a 4-role strategy -> доб.2 weight (3%) -> anchorless (§4.2)."""
    project = make_project([("k1", 100), ("k2", 80), ("k3", 60)])
    rows = gen.generate_profile_rows(project, make_strategy_safe(), 200, [])
    assert sum(r.link_qty for r in rows) == 200
    anchor_rows = [r for r in rows if r.anchor != project.url]
    # 26 + 10 + 8 = 44 anchors, anchorless = 156
    assert sum(r.link_qty for r in anchor_rows) == 44
    assert [r for r in rows if r.anchor == project.url][0].link_qty == 156


def test_manual_redistribution():
    """Freed % of missing доб.2 goes 100% to основной 1 instead of anchorless."""
    project = make_project([("k1", 100), ("k2", 80), ("k3", 60)])
    project.redistribution = {"добавочный 2": {"основной 1": 100}}
    rows = gen.generate_profile_rows(project, make_strategy_safe(), 200, [])
    assert sum(r.link_qty for r in rows) == 200
    main1 = [r for r in rows if r.keyword == "k1"][0]
    # (13% + 3%) of 200 = 32
    assert main1.link_qty == 32


def test_anchorless_format_split():
    project = make_project([("k1", 100), ("k2", 80), ("k3", 60), ("k4", 40)])
    formats = [
        gen.AnchorlessFormat("bare", "{url}", 60),
        gen.AnchorlessFormat("md", "[{domain}]({url})", 15),
    ]
    rows = gen.generate_profile_rows(project, make_strategy_safe(), 200, formats)
    assert sum(r.link_qty for r in rows) == 200
    # 150 anchorless split 60:15 -> 120 + 30
    anchor_kw = {"k1", "k2", "k3", "k4"}
    anchorless_rows = [r for r in rows if r.keyword not in anchor_kw]
    counts = sorted(r.link_qty for r in anchorless_rows)
    assert counts == [30, 120]


def test_crowd_is_all_anchorless():
    project = make_project([("k1", 100)])
    rows = gen.generate_crowd_rows(project, 170, [])
    assert len(rows) == 1
    assert rows[0].link_qty == 170
    assert rows[0].anchor == project.url


def test_internal_pages():
    project = make_project([])
    project.brand = "betalice"
    project.internal_language = "de"
    project.internal_pages = [gen.InternalPage("app", "/app/"), gen.InternalPage("withdraw", "/withdraw/")]
    project.suffix_lookup = {"app": {"de": "app"}, "withdraw": {"de": "auszahlung"}}
    rows = gen.generate_internal_rows(project)
    assert rows[0].anchor == "betalice app"
    assert rows[0].url == "https://cowboyspin-ceska.org/app/"
    assert rows[1].anchor == "betalice auszahlung"
    assert all(r.link_qty == 1 for r in rows)


def test_determinism():
    project = make_project([("k1", 100), ("k2", 80), ("k3", 60), ("k4", 40)])
    strat = make_strategy_safe()
    a = gen.generate_profile_rows(project, strat, 281, [])
    b = gen.generate_profile_rows(project, strat, 281, [])
    assert [(r.link_qty, r.anchor) for r in a] == [(r.link_qty, r.anchor) for r in b]
    assert sum(r.link_qty for r in a) == 281


def test_validate_strategy_sum():
    assert gen.validate_strategy_sum(75, [gen.Role("a", 13), gen.Role("b", 5), gen.Role("c", 4), gen.Role("d", 3)]) is None
    assert gen.validate_strategy_sum(70, [gen.Role("a", 10)]) is not None
