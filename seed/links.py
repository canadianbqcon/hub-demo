"""Cross-database link check, called by seed.py after every module ran.

check(pristine) returns a list of broken-link descriptions (empty when fine). The links are
by convention, not foreign keys, so each rule is written to pass when nothing is linked:
  tasks -> jobs     an "application #N" / "/jobs/?id=N" reference, a "<Company> application",
                    "recruiter at <Company>" or "for the <Company> ... role" must name a company in jobs.applications
  trips <-> purchases   "trip #N" in purchases text and "purchase #N" / "decision #N" in trips text must name a row;
                    "<Place> trip" in purchases text must match a trip name or destination
  gmail_item -> mail    every automations gmail_item must point at a message in mail.db
Self-check: python3 links.py
"""
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

_STOP = {"the", "this", "next", "our", "my", "a", "each", "every", "last", "first", "group", "road", "day", "long", "short", "weekend", "one", "your", "that"}


def _rows(pristine, db, table, cols):
    """Rows of the columns that exist; [] when the db or table is absent."""
    path = Path(pristine) / f"{db}.db"
    if not path.exists():
        return []
    con = sqlite3.connect(path)
    try:
        have = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
        use = [c for c in cols if c in have]
        if not use:
            return []
        return [dict(zip(use, r)) for r in con.execute(f'SELECT {",".join(use)} FROM "{table}"')]
    finally:
        con.close()


def _text(r, *keys):
    return " ".join(str(r.get(k) or "") for k in keys)


def _same(a, b):
    a, b = a.lower().strip(), b.lower().strip()
    return bool(a and b) and (a in b or b in a)


def check(pristine) -> list[str]:
    broken = []
    apps = _rows(pristine, "jobs", "applications", ["id", "company"])
    app_ids = {a["id"] for a in apps}
    companies = [a["company"] for a in apps if a.get("company")]
    for t in _rows(pristine, "tasks", "tasks", ["task_key", "title", "description"]):
        txt = _text(t, "title", "description")
        for m in re.finditer(r"(?:application\s*#?|/jobs/\?id=)(\d+)", txt, re.I):
            if app_ids and int(m.group(1)) not in app_ids:
                broken.append(f"task {t.get('task_key')!r} names application {m.group(1)}, not in jobs.applications")
        if not companies:
            continue
        for pat in (r"(?:submit|send|finish|file) the (.+?) application", r"recruiter at (.+?)(?:[.,;]|$)", r"for the (.+?) (?:\w+ )?role"):
            for m in re.finditer(pat, t.get("title") or "", re.I):
                if not any(_same(m.group(1), c) for c in companies):
                    broken.append(f"task {t.get('task_key')!r} mentions {m.group(1)!r}, no such company in jobs.applications")

    trips = _rows(pristine, "trips", "trips", ["id", "name", "destination", "notes", "trip_interests"])
    trip_ids = {t["id"] for t in trips}
    places = [str(t.get(k) or "") for t in trips for k in ("name", "destination")]
    dec_ids = {d["id"] for d in _rows(pristine, "purchases", "decisions", ["id"])}
    ptext = [(f"purchases.decisions {d.get('id')}", _text(d, "name", "use_case", "use_context", "notes", "wiki_slug"))
             for d in _rows(pristine, "purchases", "decisions", ["id", "name", "use_case", "use_context", "notes", "wiki_slug"])]
    ptext += [(f"purchases.projects {p.get('name')!r}", _text(p, "name", "notes")) for p in _rows(pristine, "purchases", "projects", ["name", "notes"])]
    ptext += [(f"purchases.orders {o.get('id')}", _text(o, "item", "notes")) for o in _rows(pristine, "purchases", "orders", ["id", "item", "notes"])]
    for who, txt in ptext:
        for m in re.finditer(r"trip\s*#(\d+)", txt, re.I):
            if trips and int(m.group(1)) not in trip_ids:
                broken.append(f"{who} names trip {m.group(1)}, not in trips.trips")
        for m in re.finditer(r"\b([A-Z][a-z]+) trip\b", txt):
            if trips and m.group(1).lower() not in _STOP and not any(m.group(1).lower() in p.lower() for p in places):
                broken.append(f"{who} mentions the {m.group(1)} trip, no matching trip in trips.trips")
    for t in trips:
        for m in re.finditer(r"(?:purchase|decision)\s*#(\d+)", _text(t, "notes", "trip_interests"), re.I):
            if dec_ids and int(m.group(1)) not in dec_ids:
                broken.append(f"trip {t.get('id')} names purchase decision {m.group(1)}, not in purchases.decisions")

    mail_ids = {m["id"] for m in _rows(pristine, "mail", "message", ["id"])}
    if mail_ids:
        for g in _rows(pristine, "automations", "gmail_item", ["id", "msg_id"]):
            if g["msg_id"] not in mail_ids:
                broken.append(f"automations.gmail_item {g['id']} points at message {g['msg_id']}, not in mail.db")
    return broken


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)

        def mk(db, sql):
            c = sqlite3.connect(d / f"{db}.db")
            c.executescript(sql)
            c.commit()
            c.close()

        mk("jobs", "CREATE TABLE applications(id INTEGER, company TEXT); INSERT INTO applications VALUES (1,'Harbor & Pine');")
        mk("tasks", "CREATE TABLE tasks(task_key TEXT,title TEXT,description TEXT);"
                    "INSERT INTO tasks VALUES ('a','Submit the Harbor & Pine application',''),('b','Buy milk','');")
        mk("trips", "CREATE TABLE trips(id INTEGER,name TEXT,destination TEXT,notes TEXT,trip_interests TEXT); INSERT INTO trips VALUES (1,'Lisbon','Portugal','','');")
        mk("purchases", "CREATE TABLE decisions(id INTEGER,name TEXT,use_context TEXT); INSERT INTO decisions VALUES (1,'Plug adapter','for the Lisbon trip');")
        assert check(d) == [], check(d)
        mk("jobs", "UPDATE applications SET company='Other Co';")
        assert any("Harbor" in b for b in check(d)), "a task naming a missing company is caught"
        mk("jobs", "UPDATE applications SET company='Harbor & Pine';")
        mk("purchases", "UPDATE decisions SET use_context='for the Denver trip';")
        assert any("Denver" in b for b in check(d)), "a purchase naming a missing trip is caught"
        mk("purchases", "UPDATE decisions SET use_context='see trip #9';")
        assert any("trip 9" in b for b in check(d))
        assert check(Path(tempfile.mkdtemp())) == [], "no databases is vacuously fine"
    print("ok")
    sys.exit(0)
