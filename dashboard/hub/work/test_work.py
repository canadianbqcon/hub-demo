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
