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
    assert sorted(names) == sorted(modules) and len(set(names)) == len(names) == 19
    assert set(d["tour"]) <= set(names) and len(d["tour"]) == 7


def test_every_entry_has_try_and_a_live_link():
    for p in guide_api.load()["pages"]:
        assert p["try"] and all(t.strip() for t in p["try"]), p["name"]
        assert p["what"].strip() and p["ai"].strip(), p["name"]
        assert client.get(p["href"]).status_code == 200, p["href"]


def test_guide_is_first_in_module_menu():
    assert MODULES[0]["href"] == "/guide/"
