import app as hub_app

def test_work_index_serves_react_shell():
    client = hub_app.app.test_client()
    r = client.get("/work/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'id="root"' in body
    # the shell went through the /jsx/ transpile route; the old /work/static/
    # path still serves the raw file, so asserting on it passed while testing
    # nothing about what the page loads.
    assert "/jsx/work/frontend/static/work.jsx" in body

def test_modules_work_in_career_and_no_barback_tile():
    mods = {m["name"]: m for m in hub_app._MODULES}
    assert "barback" not in mods                     # standalone tile removed
    assert mods["work"]["tier"] == "career"
    assert mods["work"]["href"] == "/work/"
    assert mods["work"]["meta"] == "→ /work"

def test_hours_cross_midnight():
    from work.api import _hours
    assert _hours("16:30", "00:00") == 7.5
    assert _hours("21:00", "03:00") == 6.0
    assert _hours("16:30", "23:30") == 7.0

def test_summary_endpoint_shape():
    r = hub_app.app.test_client().get("/work/api/summary")
    assert r.status_code == 200
    d = r.get_json()
    assert set(d) == {"today", "up", "last_pay", "ytd", "paid", "tools"}
    assert [t[0] for t in d["tools"]] == ["Open", "Close", "Batch prep", "Cocktails", "Map", "Stock"]
    assert all(u["date"] >= d["today"] for u in d["up"])
