"""Page matrix (spec Check 4, plan Task 11). Run from the export root:
DEMO_MODE=1 VAULT_PATH=<export>/demo-vault python3 -m pytest tests/demo/test_demo_matrix.py -q

page_apis.json is the list of GET calls each page makes on load, recorded by a
headless browser. Every page answers 200 HTML; every call answers 200 JSON with
something in it, or, when it is a switched-off outside service, 403 with the demo
note. Then one write per module that reads back.
"""
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
HUB = HERE.parents[1] / "dashboard" / "hub"
assert os.environ.get("DEMO_MODE") == "1", "run with DEMO_MODE=1"
os.chdir(HUB)
sys.path.insert(0, str(HUB))
import app as hub_app  # noqa: E402
import demo_mode  # noqa: E402

client = hub_app.app.test_client()
PAGES = json.loads((HERE / "page_apis.json").read_text())
CALLS = sorted({(page, url) for page, urls in PAGES.items() for url in urls})


def _class(url: str) -> str:
    adapter = hub_app.app.url_map.bind("localhost")
    rule, _ = adapter.match(url.split("?")[0], method="GET", return_rule=True)
    return demo_mode.ENDPOINTS[f"GET {rule.rule}"]["class"]


def _has_rows(data) -> bool:
    """Something a page would list: a non-empty list anywhere, or any non-empty value."""
    if isinstance(data, list):
        return bool(data)
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if lists:
            return any(lists) or any(_has_rows(v) for v in data.values() if isinstance(v, dict))
        return any(v not in (None, "", 0, {}, False) for v in data.values())
    return data not in (None, "")


# Status reads, not lists: a seeded one says {"empty": False, ...} with nothing to list.
STATUS_ONLY = {"/news/api/status"}


def test_reset_seeded_the_data():
    assert demo_mode.reset(), "reset did not run"


@pytest.mark.parametrize("page", sorted(PAGES))
def test_page_200_html(page):
    r = client.get(page)
    assert r.status_code == 200, (page, r.status_code)
    assert r.mimetype == "text/html"


@pytest.mark.parametrize("page,url", CALLS)
def test_page_api(page, url):
    r = client.get(url)
    if _class(url) == "integration":
        assert r.status_code == 403 and "demo" in (r.get_json(silent=True) or {}), (url, r.status_code)
        return
    assert r.status_code == 200, (page, url, r.status_code, r.get_data(as_text=True)[:300])
    data = r.get_json(silent=True)
    assert data is not None, (url, "not JSON")
    if url in STATUS_ONLY:
        return
    assert _has_rows(data), (page, url, "empty", str(data)[:300])


# (method, url, json body, GET that must then contain the marker). One per module
# with a local write; read-only pages (capabilities, inventory, artifacts, viewer,
# blueprints, vault map) have none.
MARK = "Matrix check row"
WRITES = [
    ("home", "POST", "/api/tasks/add", {"name": MARK}, "/api/home"),
    ("checklists", "POST", "/checklists/api/checklists", {"name": MARK}, "/checklists/api/checklists"),
    ("purchases", "POST", "/purchases/api/projects", {"name": MARK}, "/purchases/api/projects"),
    ("jobs", "POST", "/jobs/api/applications", {"company": MARK, "role": "Analyst"}, "/jobs/api/applications"),
    ("finances", "POST", "/finances/api/owed", {"person": MARK, "what": "Lunch", "amount": 12}, "/finances/api/owed"),
    ("news", "POST", "/news/api/topics", {"kind": "keyword", "query": MARK}, "/news/api/topics"),
    ("trips", "POST", "/trips/api/trips", {"name": MARK}, "/trips/api/trips"),
    ("workbench", "POST", "/workbench/api/decide",
     {"slug": "matrix-check", "kind": "plan", "verdict": "abandoned", "comment": MARK}, "/workbench/api/history"),
]


@pytest.mark.parametrize("module,method,url,body,readback", WRITES, ids=[w[0] for w in WRITES])
def test_write_reads_back(module, method, url, body, readback):
    r = client.open(url, method=method, json=body)
    assert r.status_code in (200, 201), (module, r.status_code, r.get_data(as_text=True)[:300])
    got = client.get(readback)
    # the planner lowercases task names in its API
    assert got.status_code == 200 and MARK.lower() in got.get_data(as_text=True).lower(), (module, readback)
