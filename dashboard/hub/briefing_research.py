"""Write path for the /before-you-go skill (weekly, Hub scheduler).

  list            next 7 days of events on writable calendars that carry no
                  bring:/prep: lines yet and were never checked, each with the
                  kit the Today card already gives it (from briefing.logic.js)
  write ID [--cal C] [--bring X]... [--prep Y]...
                  append `bring: X` / `prep: Y` lines to that event's description
                  and mark it checked; with no items it only marks it checked

Only appends. Titles, colors and existing description text are never touched.
The checked mark is a private extended property, so it never shows in the event.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".config" / "vault-api"))
from services import calendar  # noqa: E402

HERE = Path(__file__).resolve().parent
LOGIC = HERE / "static" / "js" / "briefing.logic.js"
LABEL_RE = re.compile(r"(?im)^\s*(bring|prep)\s*:")
MARK = "byg_checked"
SKIP_NAME = re.compile(r"(?i)\bshift\b|barback|birthday|^✓")   # shifts: nothing (2026-11-09); birthdays: denied


def _kits(events: list[dict]) -> list[dict]:
    js = ("const L=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d)"
          ".on('end',()=>console.log(JSON.stringify(JSON.parse(s).map(e=>L.eventKits(e)))))")
    out = subprocess.run(["node", "-e", js, str(LOGIC)], input=json.dumps(events),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def list_events(days: int = 7) -> list[dict]:
    c = calendar()
    now = datetime.now(timezone.utc)
    found = []
    for cal in c.calendarList().list().execute().get("items", []):
        if cal.get("accessRole") not in ("owner", "writer"):
            continue   # Partiful, holidays: subscriptions we cannot write
        items = c.events().list(calendarId=cal["id"], timeMin=now.isoformat(),
                                timeMax=(now + timedelta(days=days)).isoformat(),
                                singleEvents=True, maxResults=500).execute().get("items", [])
        for e in items:
            name, desc = e.get("summary", ""), e.get("description", "")
            if SKIP_NAME.search(name) or LABEL_RE.search(desc):
                continue
            if (e.get("extendedProperties", {}).get("private", {}) or {}).get(MARK):
                continue
            found.append({"id": e["id"], "cal": cal["id"], "name": name, "location": e.get("location", ""),
                          "description": desc[:1500], "start": e["start"].get("dateTime") or e["start"].get("date")})
    for ev, kit in zip(found, _kits(found)):
        ev["kit"] = kit
    return found


def write(event_id: str, cal: str, bring: list[str], prep: list[str]) -> dict:
    c = calendar()
    ev = c.events().get(calendarId=cal, eventId=event_id).execute()
    lines = [f"bring: {b.strip()}" for b in bring if b.strip()] + [f"prep: {p.strip()}" for p in prep if p.strip()]
    body: dict = {"extendedProperties": {"private": {MARK: datetime.now().date().isoformat()}}}
    if lines:
        desc = (ev.get("description") or "").rstrip()
        body["description"] = (desc + "\n\n" if desc else "") + "\n".join(lines)
    c.events().patch(calendarId=cal, eventId=event_id, body=body).execute()
    return {"id": event_id, "added": lines}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    w = sub.add_parser("write")
    w.add_argument("id")
    w.add_argument("--cal", default="primary")
    w.add_argument("--bring", action="append", default=[])
    w.add_argument("--prep", action="append", default=[])
    a = ap.parse_args(argv)
    if a.cmd == "list":
        print(json.dumps(list_events(), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(write(a.id, a.cal, a.bring, a.prep), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
