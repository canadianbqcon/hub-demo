import pytest

import app as hub_app
from gaming import api


def _by_id(d):
    return {g["id"]: g for g in d["games"]}


def test_games_and_their_modules():
    d = api.summary()
    g = _by_id(d)
    assert [x["id"] for x in d["games"]] == ["league", "cs2", "clash"]
    assert [m["url"] for m in g["league"]["modules"]] == [
        "/forge/", "/forge/patch", "/forge/stats", "/forge/draft", "/forge/edit"]
    assert [m["url"] for m in g["cs2"]["modules"]] == ["/ledger/"]
    assert [m["url"] for m in g["clash"]["modules"]] == [
        "/clash/", "/clash/profile", "/clash/war", "/clash/plan", "/clash/layouts"]
    assert g["league"]["launch"][1] == "/forge/" and g["cs2"]["launch"][1] == "/ledger/"
    assert all(x["count"] == len(x["modules"]) for x in d["games"])
    # modules are Hub pages, never outside artifact links
    assert all(m["url"].startswith("/") for x in d["games"] for m in x["modules"])


def test_stats_come_from_the_data(monkeypatch):
    monkeypatch.setattr(api, "_league_stats", lambda: {"patch": "26.22", "champions": 120, "sets": 4,
                                                       "rank": "Gold 1 66 LP", "record": "120W 111L"})
    monkeypatch.setattr(api, "_cs2_stats", lambda: {"mark": "$1,165.31", "items": 109})
    g = _by_id(api.summary())
    by_url = {m["url"]: m for m in g["league"]["modules"]}
    assert by_url["/forge/"]["stat"] == "4 saved sets"
    assert by_url["/forge/patch"]["stat"] == "Patch 26.22"
    assert by_url["/forge/stats"]["stat"] == "120W 111L"
    assert by_url["/forge/stats"]["desc"] == "Your rank, match history and champion record"
    assert g["league"]["headline"] == {"label": "Solo / Duo", "value": "Gold 1 66 LP"}
    assert g["cs2"]["modules"][0]["stat"] == "$1,165.31 across 109 items"
    assert g["cs2"]["headline"] == {"label": "Inventory", "value": "$1,165.31"}


def test_rank_reads_the_cached_profile(monkeypatch, tmp_path):
    (tmp_path / "forge-me.json").write_text('{"ranks": [{"queue": "FLEXRANKED", "tier": "BRONZE", "division": 2, '
                                            '"lp": 5, "win": 5, "lose": 3}, {"queue": "SOLORANKED", "tier": "GOLD", '
                                            '"division": 1, "lp": 66, "win": 120, "lose": 111}]}')
    monkeypatch.setattr(api, "_DATA", tmp_path)
    assert api._solo_rank() == {"rank": "Gold 1 66 LP", "record": "120W 111L"}
    (tmp_path / "forge-me.json").write_text('{"ranks": []}')
    assert api._solo_rank() == {}


def test_no_rank_falls_back_to_patch(monkeypatch):
    monkeypatch.setattr(api, "_league_stats", lambda: {"patch": "26.22", "champions": 120, "sets": 4})
    monkeypatch.setattr(api, "_cs2_stats", lambda: {})
    g = _by_id(api.summary())
    assert g["league"]["headline"] == {"label": "Patch", "value": "26.22"}
    assert {m["url"]: m for m in g["league"]["modules"]}["/forge/stats"]["stat"] == ""


@pytest.mark.parametrize("which", ["_league_stats", "_cs2_stats", "_clash_stats"])
def test_a_failing_source_leaves_stat_blank_not_a_500(monkeypatch, which):
    def boom():
        raise RuntimeError("source down")
    monkeypatch.setattr(api, which, boom)
    r = hub_app.app.test_client().get("/gaming/api/summary")
    assert r.status_code == 200
    d = r.get_json()
    assert [x["id"] for x in d["games"]] == ["league", "cs2", "clash"]
    assert all(m["stat"] == "" for x in d["games"] for m in x["modules"]
               if x["id"] == {"_league_stats": "league", "_cs2_stats": "cs2", "_clash_stats": "clash"}[which])


def test_summary_endpoint_shape():
    r = hub_app.app.test_client().get("/gaming/api/summary")
    assert r.status_code == 200
    assert set(r.get_json()) == {"games"}


def test_page_renders_shell():
    r = hub_app.app.test_client().get("/gaming/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'id="root"' in body
    assert "/jsx/gaming/frontend/static/gaming.jsx" in body


def test_gaming_module_registered():
    from hub_modules import MODULES
    m = [x for x in MODULES if x["name"] == "gaming"]
    assert len(m) == 1 and m[0]["href"] == "/gaming/" and m[0]["tier"] == "life"


def test_artifacts_page_keeps_every_row_including_games():
    d = hub_app.app.test_client().get("/artifacts/api/data").get_json()
    assert "moved" not in d
    assert any(a.get("category") == "Games" for a in d["artifacts"])
    assert not any("game" in a for a in d["artifacts"])


def test_clash_band_listed():
    g = _by_id(api.summary())["clash"]
    assert g["name"] == "Clash of Clans" and g["count"] == 5
    assert [m["title"] for m in g["modules"]] == ["Tracker", "Profile", "War", "Plan", "Layouts"]


def test_clash_stat_blank_when_db_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_DATA", tmp_path)
    monkeypatch.setattr(api, "_league_stats", lambda: {"patch": "26.22", "sets": 4})
    monkeypatch.setattr(api, "_cs2_stats", lambda: {"mark": "$1.00", "items": 1})
    g = _by_id(api.summary())
    assert not (tmp_path / "clash.db").exists()
    assert all(m["stat"] == "" for m in g["clash"]["modules"]) and g["clash"]["headline"] is None
    assert g["league"]["modules"][0]["stat"] == "4 saved sets"
    assert g["cs2"]["modules"][0]["stat"] == "$1.00 across 1 items"


def test_clash_stat_counts_busy_builders(monkeypatch, tmp_path):
    import sqlite3
    from datetime import datetime, timedelta, timezone
    f = lambda d: (datetime.now(timezone.utc) + timedelta(hours=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
    c = sqlite3.connect(tmp_path / "clash.db")
    c.executescript("""CREATE TABLE account(tag TEXT, builders INTEGER, updated_at TEXT);
        CREATE TABLE upgrade(tag TEXT, facility TEXT, finishes_at TEXT);
        INSERT INTO account VALUES ('#A', 5, '2026-01-01'), ('#B', 6, '2026-02-01');""")
    c.executemany("INSERT INTO upgrade VALUES (?,?,?)", [("#B", "builder", f(5)), ("#B", "builder", f(30)),
                  ("#B", "builder", f(-1)), ("#B", "lab", f(2)), ("#A", "builder", f(1))])
    c.commit(); c.close()
    monkeypatch.setattr(api, "_DATA", tmp_path)
    g = _by_id(api.summary())["clash"]
    assert g["headline"] == {"label": "Builders busy", "value": "2 of 6"}
    assert g["modules"][0]["stat"].startswith("2 of 6 builders busy, next in 4h")
