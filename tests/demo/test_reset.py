"""Reset (spec Check 6) on a two-table fixture. Run from the export root:
DEMO_MODE=1 python3 -m pytest tests/demo/test_reset.py -q

Uses a tiny Flask app, not the Hub, so the fixture stays two tables. Run it
after test_demo_mode.py (it repoints VAULT_PATH for the rest of the process).
"""
import datetime as dt
import sqlite3
import sys
import threading
from pathlib import Path

import pytest
from flask import Flask

HUB = Path(__file__).resolve().parents[2] / "dashboard" / "hub"
sys.path.insert(0, str(HUB))
import demo_mode  # noqa: E402

UTC = dt.timezone.utc
DAY1 = dt.datetime(2030, 1, 10, 23, 59, tzinfo=UTC)
DAY2 = dt.datetime(2030, 1, 11, 0, 1, tzinfo=UTC)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    pristine = tmp_path / "pristine"
    pristine.mkdir()
    con = sqlite3.connect(pristine / "a.db")
    con.executescript("""
        CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, due TEXT, stamp TEXT);
        CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT);
        INSERT INTO tasks (title, due, stamp) VALUES
            ('overdue', '@d-1', '@t-3'), ('today', '@d0', '@d0 14:30:00'), ('later', '@d+7', NULL);
        INSERT INTO notes (body) VALUES ('due @d+2, mail me@example.com');
    """)
    con.commit()
    con.close()
    (pristine / "wiki" / "notes").mkdir(parents=True)
    (pristine / "wiki" / "notes" / "n.md").write_text("pristine\n")
    (pristine / "data" / "inventory").mkdir(parents=True)
    (pristine / "data" / "inventory" / "x.json").write_text("{}\n")
    demo_mode._state.update(resetting=False, inflight=0, last=None, ready=False, failed_at=None)
    yield tmp_path
    demo_mode._state.update(resetting=False, inflight=0, last=None, ready=False, failed_at=None)


def rows(vault, sql):
    con = sqlite3.connect(vault / "data" / "a.db")
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def counts(vault):
    return {t: rows(vault, f"SELECT count(*) FROM {t}")[0][0] for t in ("tasks", "notes")}


@pytest.fixture
def client(vault, monkeypatch):
    app = Flask("reset-test")
    demo_mode.install(app)

    @app.post("/w")
    def write():
        con = sqlite3.connect(vault / "data" / "a.db", timeout=30)
        con.execute("INSERT INTO notes (body) VALUES ('visitor')")
        con.commit()
        con.close()
        return "ok"

    @app.get("/r")
    def read():
        return "ok"

    @app.get("/i")
    def outside():
        return "reached"

    @app.post("/p")
    def pinned():
        return "ok"

    monkeypatch.setattr(demo_mode, "ENDPOINTS",
                        {"POST /w": {"class": "local-write"}, "GET /r": {"class": "read"},
                         "GET /i": {"class": "integration"},
                         "POST /p": {"class": "local-write", "path-pinned": True}})
    return app.test_client()


def test_offsets_materialize_against_reset_day(vault):
    assert demo_mode.reset(DAY1)
    got = dict(rows(vault, "SELECT title, due FROM tasks"))
    assert got == {"overdue": "2030-01-09", "today": "2030-01-10", "later": "2030-01-17"}
    stamps = dict(rows(vault, "SELECT title, stamp FROM tasks"))
    assert stamps["overdue"] == "2030-01-10 20:59:00"
    assert stamps["today"] == "2030-01-10 14:30:00"
    assert rows(vault, "SELECT body FROM notes") == [("due 2030-01-12, mail me@example.com",)]


def test_write_gone_after_forced_reset(vault, client):
    assert demo_mode.reset(DAY1)
    before = counts(vault)
    assert client.post("/w").status_code == 200
    (vault / "wiki" / "notes" / "n.md").write_text("edited\n")
    assert counts(vault)["notes"] == before["notes"] + 1
    assert demo_mode.reset(DAY1)
    assert counts(vault) == before
    assert (vault / "wiki" / "notes" / "n.md").read_text() == "pristine\n"
    (vault / "data" / "inventory" / "x.json").write_text("edited\n")
    assert demo_mode.reset(DAY1)
    assert (vault / "data" / "inventory" / "x.json").read_text() == "{}\n"


def test_three_resets_identical(vault):
    seen = []
    for _ in range(3):
        assert demo_mode.reset(DAY1)
        seen.append((counts(vault), rows(vault, "SELECT * FROM tasks ORDER BY id")))
    assert seen[0] == seen[1] == seen[2]


def test_midnight_utc_triggers_reset_on_next_request(vault, client, monkeypatch):
    monkeypatch.setattr(demo_mode, "_now", lambda: DAY1)
    assert client.get("/r").status_code == 200  # boot-style first reset
    assert client.post("/w").status_code == 200
    n = counts(vault)["notes"]
    assert client.get("/r").status_code == 200  # same day: no reset
    assert counts(vault)["notes"] == n
    monkeypatch.setattr(demo_mode, "_now", lambda: DAY2)
    assert client.get("/r").status_code == 200
    assert counts(vault)["notes"] == n - 1
    assert demo_mode._state["last"] == DAY2
    assert dict(rows(vault, "SELECT title, due FROM tasks"))["today"] == "2030-01-11"


def test_concurrent_writers_during_reset(vault, client):
    assert demo_mode.reset(DAY1)
    codes, errors = [], []

    def writer():
        try:
            for _ in range(25):
                codes.append(client.post("/w").status_code)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for t in threads:
        t.start()
    for _ in range(5):
        assert demo_mode.reset(DAY1) in (True, False)
    for t in threads:
        t.join(60)
    assert not errors
    assert len(codes) == 50 and set(codes) <= {200, 503}
    assert rows(vault, "PRAGMA integrity_check") == [("ok",)]
    assert demo_mode._state["inflight"] == 0


def test_failed_integrity_serves_503_until_retry(vault, client, monkeypatch):
    monkeypatch.setattr(demo_mode, "_now", lambda: DAY1)
    real = demo_mode._restore

    def broken(now):
        raise RuntimeError("integrity_check failed: ['a.db']")

    monkeypatch.setattr(demo_mode, "_restore", broken)
    r = client.get("/r")
    assert r.status_code == 503 and b"resetting" in r.data
    monkeypatch.setattr(demo_mode, "_restore", real)
    assert client.get("/r").status_code == 503  # inside the retry backoff
    later = DAY1 + dt.timedelta(seconds=demo_mode.RETRY_AFTER + 1)
    monkeypatch.setattr(demo_mode, "_now", lambda: later)
    assert client.get("/r").status_code == 200


def test_visitor_files_removed_by_reset(vault):
    assert demo_mode.reset(DAY1)
    (vault / "data" / "upload.png").write_bytes(b"x")
    (vault / "data" / "inventory" / "new.json").write_text("{}")
    (vault / "stray.txt").write_text("x")
    assert demo_mode.reset(DAY1)
    assert not (vault / "data" / "upload.png").exists()
    assert not (vault / "data" / "inventory" / "new.json").exists()
    assert not (vault / "stray.txt").exists()
    assert (vault / "data" / "a.db").exists() and (vault / "data" / "inventory" / "x.json").exists()


def test_reset_deferred_while_a_request_is_in_flight(vault):
    assert demo_mode.reset(DAY1)
    demo_mode._state["inflight"] = 1
    try:
        assert demo_mode.reset(DAY2, wait=0.1) is False
        assert demo_mode._state["ready"] and demo_mode._state["last"] == DAY1
    finally:
        demo_mode._state["inflight"] = 0


def test_head_is_guarded_like_get(vault, client):
    r = client.head("/i")
    assert r.status_code == 403


def test_path_pin_sees_nested_repeated_and_forced_values(vault, client):
    assert client.post("/p", json={"a": "ok"}).status_code == 200
    assert client.post("/p", json={"paths": ["../../etc/passwd"]}).status_code == 400
    assert client.post("/p", json={"o": {"file": "/etc/passwd"}}).status_code == 400
    assert client.post("/p?path=ok&path=/etc/passwd").status_code == 400
    assert client.post("/p", data='{"f": "../x"}', content_type="text/plain").status_code == 400


@pytest.mark.parametrize("how", ["empty", "missing"])
def test_missing_or_empty_pristine_deletes_nothing(vault, how):
    import shutil
    assert demo_mode.reset(DAY1)
    (vault / "stray.txt").write_text("x")
    if how == "missing":
        shutil.rmtree(vault / "pristine")
    else:
        for db in (vault / "pristine").glob("*.db"):
            db.unlink()
    assert demo_mode.reset(DAY1) is False
    assert (vault / "stray.txt").exists() and (vault / "data" / "a.db").exists()
    assert (vault / "wiki" / "notes" / "n.md").exists()


def test_deferral_keeps_a_failed_state_closed(vault):
    assert demo_mode.reset(DAY1)
    demo_mode._state["ready"] = False  # e.g. the last restore failed
    demo_mode._state["inflight"] = 1
    try:
        assert demo_mode.reset(DAY2, wait=0.1) is False
        assert demo_mode._state["ready"] is False
    finally:
        demo_mode._state["inflight"] = 0


def test_reset_clears_recipes_sweep_throttle(vault, monkeypatch):
    import types
    store = types.ModuleType("recipes.store")
    store._cache, store._stamps, store._last_sweep = {}, {}, 123.0
    monkeypatch.setitem(sys.modules, "recipes.store", store)
    assert demo_mode.reset(DAY1)
    assert store._last_sweep == float("-inf")


def test_path_pin_sees_json_keys_and_upload_names(vault, client):
    import io
    assert client.post("/p", json={"../x": 1}).status_code == 400
    r = client.post("/p", data={"f": (io.BytesIO(b"x"), "../../etc/passwd")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post("/p", data={"f": (io.BytesIO(b"x"), "ok.png")}, content_type="multipart/form-data")
    assert r.status_code == 200
