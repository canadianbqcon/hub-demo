"""Guide page (plan Task 9). Run from the export root:
DEMO_MODE=1 VAULT_PATH=<export>/demo-vault python3 -m pytest tests/demo/test_guide.py -q
"""
import os
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parents[2] / "dashboard" / "hub"
assert os.environ.get("DEMO_MODE") == "1", "run with DEMO_MODE=1"
os.chdir(HUB)
sys.path.insert(0, str(HUB))
import app as hub_app  # noqa: E402
from guide import api as guide_api  # noqa: E402
from hub_modules import MODULES  # noqa: E402

client = hub_app.app.test_client()


def test_guide_200_with_tour_and_rest():
    r = client.get("/guide/")
    assert r.status_code == 200 and r.mimetype == "text/html"
    body = r.get_data(as_text=True)
    assert "A ten-minute tour" in body and "Every other page" in body
    assert body.count('class="gd-num"') == 7
    assert guide_api.REPO_URL in body


def test_pages_cover_every_module_once():
    d = guide_api.load()
    names = [p["name"] for p in d["pages"]]
    modules = [m["name"] for m in MODULES if m["href"] != "/guide/"]
    assert sorted(names) == sorted(modules) and len(set(names)) == len(names) == len(modules)
    assert set(d["tour"]) <= set(names) and len(d["tour"]) == 7


def test_every_entry_has_try_and_a_live_link():
    for p in guide_api.load()["pages"]:
        assert p["try"] and all(t.strip() for t in p["try"]), p["name"]
        assert p["what"].strip() and p["ai"].strip(), p["name"]
        assert client.get(p["href"]).status_code == 200, p["href"]


def test_guide_is_first_in_module_menu():
    assert MODULES[0]["href"] == "/guide/"


def test_panel_fragment_carries_tour_and_refining_note():
    r = client.get("/guide/panel")
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "<script" not in body and "demo-banner" not in body
    assert body.count('class="gd-num"') == 7 and guide_api.REFINING in body


def test_panel_on_every_page_but_the_guide():
    assert 'id="demo-guide"' in client.get("/").get_data(as_text=True)
    page = client.get("/guide/").get_data(as_text=True)
    assert 'id="demo-guide"' not in page and guide_api.REFINING in page


def test_home_schedule_shows_seeded_calendar():
    import demo_mode
    days = client.get("/api/home").get_json()["SCHEDULE"]
    today = next(d for d in days if d["isToday"])
    names = [e["name"] for e in today["events"] if e["sub"] == "cal"]
    assert names == [t for off, _s, _e, t, *_ in demo_mode.CAL_EVENTS if off == 0]
    assert sum(len(d["events"]) for d in days) >= 15


def test_panel_assets_served_and_linked():
    page = client.get("/").get_data(as_text=True)
    for f in ("panel.css", "panel.js"):
        assert f"/guide/static/{f}?v=" in page
        assert client.get(f"/guide/static/{f}").status_code == 200


def test_calendar_stays_on_home_only():
    import gcal
    import home_data
    import demo_mode
    # the real gcal is untouched, so trips and tasks calendar writes stay off
    assert gcal.fetch_week_events is not demo_mode._demo_week_events
    assert home_data.gcal.fetch_week_events is demo_mode._demo_week_events
    assert all(c != "11" for *_, c in demo_mode.CAL_EVENTS)  # Tomato would become a task row
