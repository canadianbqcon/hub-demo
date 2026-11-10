#!/usr/bin/env python3
"""Sync upcoming work shifts from Google Calendar into earnings_scheduled_shifts.

The scheduled rows are what `earnings_expected_month` prices against the
historical per-day-of-week average (migration 003). Run it whenever the
calendar changes:

    python3 dashboard/hub/finances/shift_calendar.py            # sync + audit + forecast
    python3 dashboard/hub/finances/shift_calendar.py --show     # print forecast only
    python3 dashboard/hub/finances/shift_calendar.py --no-audit  # sync without the Haiku check

A job is recognised by its calendar event title, location, and Company: line.
Add a job by adding a pattern.

Pattern matching is the only thing that writes shift rows, and it is brittle by
nature: it went blind for ten days in Aug 2026 when the calendar title convention
moved the employer out of the title, and reported a confident near-empty August
the whole time. `audit()` is the backstop -- it hands the raw event titles to
Haiku and asks which read as work shifts, then reports any the matcher missed.
It never writes a shift row and never blocks the sync; a missed shift shows up
as a flag on the earnings page for a human to look at.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlite_helpers import connect as sqlite_connect  # noqa: E402
from vault_path import vault_root  # noqa: E402

# Calendar event title -> earnings.source. Case-insensitive search, not fullmatch,
# so "J&Co — Barback" and a future "J&Co — Bartender" both land on the same job.
#
# Matched against the title AND the event description's "Company:" line, because
# the calendar title convention (wiki/notes/calendar-event-conventions.md) moved
# the employer out of the title: shifts now read "Barback Shift", not
# "J&Co — Barback", with the employer only in location and the Company: line.
# Title-only matching went blind the day that convention landed and silently
# forecast zero shifts.
JOB_CALENDAR_PATTERNS = {
    "juniper-and-co": r"\bJ&C\b|\bJade & Sorrel\b",
}

# What makes an event work rather than a night out at the same bar. Only consulted
# when the employer is named outside the title -- an employer in the title is the
# legacy convention and carries the meaning by itself.
WORK_MARKER = r"\bShift\b|^\s*Role:\s*\S"

DB_PATH = vault_root() / "data" / "earnings.db"


def _conn():
    # The shared helper, not a bare sqlite3.connect: `with sqlite3.connect(...)`
    # commits on exit but never closes, so every call here leaked an fd — and the
    # long-lived Hub process eventually pinned a deleted -wal file open, which on
    # drvfs makes that name unopenable and 500s the whole earnings tab.
    return sqlite_connect(DB_PATH, "finances.shift_calendar")


def _calendar():
    # services.py lives at ~/.config/vault-api/, a machine-local credentials
    # module that is deliberately outside this repo.
    cfg = str(Path.home() / ".config" / "vault-api")
    if cfg not in sys.path:
        sys.path.insert(0, cfg)
    import services  # pyright: ignore[reportMissingImports]
    return services.calendar()


def source_for(summary: str, description: str | None = None,
               location: str | None = None) -> str | None:
    """The job this event belongs to, or None.

    Three fields are searched because none of them is reliably present alone:
    legacy events name the employer in the title, current ones name it in the
    location and sometimes in a Company: line, and the description is often
    empty. Only the Company: line of the description counts, never the whole
    body -- a dinner reservation whose notes mention the bar is not a shift.
    """
    haystack = [summary or ""]
    if re.search(WORK_MARKER, f"{summary or ''}\n{description or ''}", re.IGNORECASE | re.MULTILINE):
        company = re.search(r"^\s*Company:\s*(.+)$", description or "",
                            re.IGNORECASE | re.MULTILINE)
        haystack += [location or "", company.group(1) if company else ""]
    for source, pattern in JOB_CALENDAR_PATTERNS.items():
        if re.search(pattern, "\n".join(haystack), re.IGNORECASE):
            return source
    return None


def roster_source_for(description: str | None) -> str | None:
    """'posted' | 'assumed' | None, read off the event's own Source: line.

    Posted shifts carry 'Source: SpotOn Teamwork schedule (wk Aug 17), posted by
    Alex Park'; ones Sam projected from a recurring pattern carry
    'Source: UNVERIFIED -- projected from the recurring Friday pattern...'.
    An event with no Source: line at all returns None rather than 'posted' --
    same reason the column is nullable, an undetermined row must not claim to
    have come off a roster.
    """
    m = re.search(r"^\s*Source:\s*(.+)$", description or "", re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    return "assumed" if "UNVERIFIED" in m.group(1).upper() else "posted"


def list_events(months_ahead: int = 6, today: date | None = None,
                start: date | None = None, end: date | None = None) -> list[dict]:
    """Every primary-calendar event in the horizon, raw.

    Shared by the matcher and the audit on purpose: the check is only worth
    anything if it sees exactly the events the matcher saw and disagrees about
    them, rather than reading a differently-scoped window.

    `start`/`end` override the default today→horizon window. The forecast only
    ever looks forward, but the pay-stub reconciler needs a window that is
    entirely in the PAST -- a stub arrives days after the shifts it records.
    """
    today = today or date.today()
    horizon = today + timedelta(days=31 * months_ahead)
    lo, hi = (start or today), (end or horizon)
    cal = _calendar()
    events, page = [], None
    while True:
        resp = cal.events().list(
            calendarId="primary",
            timeMin=f"{lo.isoformat()}T00:00:00Z",
            timeMax=f"{hi.isoformat()}T00:00:00Z",
            singleEvents=True, orderBy="startTime",
            maxResults=250, pageToken=page,
        ).execute()
        events.extend(resp.get("items", []))
        page = resp.get("nextPageToken")
        if not page:
            return events


def fetch_shifts(months_ahead: int = 6, today: date | None = None,
                 events: list[dict] | None = None) -> list[dict]:
    """Calendar events matching a known job, as {source, shift_date, ...} dicts."""
    found = []
    for ev in (list_events(months_ahead, today) if events is None else events):
        source = source_for(ev.get("summary", ""), ev.get("description"),
                            ev.get("location"))
        if not source:
            continue
        start = ev["start"].get("dateTime") or ev["start"].get("date")
        end = ev["end"].get("dateTime") or ev["end"].get("date")
        # The window, not just the day: a 9pm-3am Friday and a 4:30pm-3am
        # Friday are the same date and nowhere near the same money, and the
        # pricing model needs the clock times to know which one it is.
        # All-day events carry no time, so they price by day-of-week as before.
        timed = "T" in (start or "") and "T" in (end or "")
        found.append({
            "source": source,
            "shift_date": start[:10],
            "calendar_event_id": ev.get("id"),
            "summary": ev.get("summary"),
            "start_at": start[11:16] if timed else None,
            "end_at": end[11:16] if timed else None,
            "roster_source": roster_source_for(ev.get("description")),
        })
    return found


# ── SpotOn mirror ─────────────────────────────────────────────────────────────
# SpotOn Teamwork's calendar sync writes shifts to its own "Juniper & Co's Work
# Schedule" calendar, titled "Juniper &amp; Co Barback" (HTML-escaped, by them).
# Shifts belong on Personal as "Barback Shift" (calendar-event-conventions), so
# each shift-sync run copies them over, keyed by the SpotOn event id in a private
# extended property, and unticks the SpotOn calendar so nothing shows twice.
# Only future shifts are touched: past ones get hand-corrected to actual times.

SPOTON_CAL = "Juniper & Co's Work Schedule"
JC_LOCATION = "Juniper & Co, 200 Example Ave, New York, NY 10002"


def _spoton_role(summary: str) -> str:
    """'Juniper &amp; Co Barback' -> 'Barback'."""
    import html
    s = html.unescape(summary or "").strip()
    s = re.sub(r"^(Juniper\s*(&|and)\s*Sorrel|J&Co)\s*[-—:]?\s*", "", s, flags=re.IGNORECASE)
    return s or "Barback"


def mirror_spoton(now: datetime | None = None) -> dict:
    import gcal
    svc = gcal._get_service()
    cals = [c for c in svc.calendarList().list().execute().get("items", [])
            if c.get("summary") == SPOTON_CAL]
    if not cals:
        return {"created": 0, "updated": 0, "deleted": 0, "note": "no SpotOn calendar"}
    now = now or datetime.now().astimezone()
    lo = now.astimezone().isoformat(timespec="seconds")
    hi = (now + timedelta(days=200)).astimezone().isoformat(timespec="seconds")

    def window(cal_id):
        out, page = [], None
        while True:
            r = svc.events().list(calendarId=cal_id, timeMin=lo, timeMax=hi, singleEvents=True,
                                  maxResults=250, pageToken=page).execute()
            out += r.get("items", [])
            page = r.get("nextPageToken")
            if not page:
                return out

    src = [e for c in cals for e in window(c["id"])
           if e.get("status") != "cancelled" and "dateTime" in e["start"]]
    mine = [e for e in window("primary")
            if source_for(e.get("summary", ""), e.get("description"), e.get("location"))]
    by_id = {e.get("extendedProperties", {}).get("private", {}).get("spoton_id"): e for e in mine}
    by_date = {e["start"].get("dateTime", "")[:10]: e for e in mine}
    seen, n = set(), {"created": 0, "updated": 0, "deleted": 0}

    for s in src:
        start, end = s["start"]["dateTime"], s["end"]["dateTime"]
        p = by_id.get(s["id"]) or by_date.get(start[:10])
        if p:
            seen.add(p["id"])
            patch = {}
            if p.get("extendedProperties", {}).get("private", {}).get("spoton_id") != s["id"]:
                patch["extendedProperties"] = {"private": {"spoton_id": s["id"]}}
            elif (p["start"].get("dateTime"), p["end"].get("dateTime")) != (start, end):
                # Mirrored before and SpotOn moved it: follow the roster.
                patch.update(start={"dateTime": start}, end={"dateTime": end})
            if patch:
                svc.events().patch(calendarId="primary", eventId=p["id"], body=patch).execute()
                n["updated"] += 1
            continue
        role = _spoton_role(s.get("summary"))
        made = gcal.create_event({
            "summary": f"{role} Shift",
            "location": JC_LOCATION,
            "description": f"Role: {role}\nCompany: Juniper & Co\n"
                           f"Source: SpotOn Teamwork calendar (auto-mirrored)",
            "start": {"dateTime": start}, "end": {"dateTime": end},
            "reminders": {"useDefault": False},
            "extendedProperties": {"private": {"spoton_id": s["id"]}},
        }, label="Work Shifts")
        seen.add(made["id"])
        n["created"] += 1

    # A mirrored shift SpotOn no longer lists was dropped from the roster.
    # Hand-made shifts (no spoton_id) are never deleted.
    for p in mine:
        if p["id"] not in seen and p.get("extendedProperties", {}).get("private", {}).get("spoton_id"):
            svc.events().delete(calendarId="primary", eventId=p["id"]).execute()
            n["deleted"] += 1

    for c in cals:
        if c.get("selected"):
            svc.calendarList().patch(calendarId=c["id"], body={"selected": False}).execute()
    return n


# ── The Haiku backstop ────────────────────────────────────────────────────────
# Report-only. Nothing below writes a shift row, and every failure path here is
# swallowed: a check that can break the sync it is checking is worse than no
# check. Haiku, not a bigger model, because "is this title a work shift" is a
# reading task with no judgment in it.

AUDIT_PATH = vault_root() / "data" / "shift-sync-audit.json"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local" / "bin" / "claude"))

AUDIT_PROMPT = """You are auditing a calendar sync. Below are calendar events, one per line, as
DATE | TITLE.

Return the dates of every event that reads as a scheduled WORK SHIFT -- a shift
at a job the person is rostered for (barback, bartender, server, kitchen, and
the like). Do NOT include social events, travel, flights, appointments, bill
reminders, birthdays, or anything held AT a venue without being work.

Reply with a JSON array of date strings and nothing else. Example: ["2026-08-14"]
If none qualify, reply [].

EVENTS:
"""


def _ask_haiku(prompt: str, timeout: int = 120) -> str:
    out = subprocess.run(
        [CLAUDE_BIN, "-p", prompt, "--model", "haiku"],
        capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL,   # headless claude hangs on an inherited stdin
        cwd=str(vault_root()),
    )
    if out.returncode != 0:
        raise RuntimeError(f"claude exited {out.returncode}: {out.stderr[:200]}")
    return out.stdout


def _parse_dates(raw: str) -> list[str]:
    """The JSON array out of a reply that may be wrapped in prose or a fence."""
    m = re.search(r"\[.*?\]", raw, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON array in reply: {raw[:200]}")
    return [d for d in json.loads(m.group(0))
            if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]


def _titles(events: list[dict]) -> list[str]:
    lines = []
    for ev in events:
        start = ev["start"].get("dateTime") or ev["start"].get("date") or ""
        lines.append(f"{start[:10]} | {ev.get('summary') or '(no title)'}")
    return lines


def audit(events: list[dict], matched: list[dict], force: bool = False) -> dict:
    """Ask Haiku which events look like shifts, and report the ones we missed.

    Re-runs only when the calendar's titles actually change, keyed by a hash of
    the event lines. The sync fires six times a day and the answer cannot move
    unless its input does, so the other five runs read the cached verdict.
    """
    lines = _titles(events)
    fingerprint = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]
    previous = read_audit()
    if not force and previous.get("fingerprint") == fingerprint:
        return previous

    have = {s["shift_date"] for s in matched}
    result = {"fingerprint": fingerprint, "checked_at": datetime.now().isoformat(timespec="seconds"),
              "missed": [], "error": None}
    try:
        flagged = _parse_dates(_ask_haiku(AUDIT_PROMPT + "\n".join(lines)))
        by_date = {ln[:10]: ln[13:] for ln in lines}
        result["missed"] = [{"date": d, "summary": by_date.get(d, "")}
                            for d in sorted(set(flagged) - have)]
    except Exception as exc:
        # A failed check reports itself as failed. Silently returning "nothing
        # missed" would be the exact lie this whole backstop exists to catch.
        result["error"] = f"{type(exc).__name__}: {exc}"[:200]
    try:
        AUDIT_PATH.write_text(json.dumps(result, indent=2))
    except Exception as e:  # an unwritable report file must not take the sync down with it
        print(f"shift audit write failed: {e}", file=sys.stderr)
    return result


def read_audit() -> dict:
    try:
        return json.loads(AUDIT_PATH.read_text())
    except Exception as e:  # missing or corrupt report reads as no audit yet
        print(f"shift audit read failed: {e}", file=sys.stderr)
        return {}


def replace_scheduled(shifts: list[dict], today: date | None = None) -> int:
    """Full resync of today-and-later rows for every job we know how to read.

    Upsert, then drop whatever the calendar no longer lists, so a cancelled shift
    still disappears. It is deliberately NOT a delete-everything-and-reinsert:
    that reassigns row ids, which would cascade away the crew roster on
    earnings_shift_crew and wipe hand-set columns like shift_kind ('buyout')
    that the calendar knows nothing about. The calendar owns the window and the
    event id; everything else on the row survives a resync untouched.

    Past rows are left alone: they are the actuals' scaffolding, not a forecast.
    """
    # Back the cutoff up to this week's Monday, not today: a benefit week is priced
    # off the whole Mon-Sun block, so dropping shifts already worked earlier this
    # week would under-report its hours and over-predict that week's UI payment.
    t = today or date.today()
    cutoff = (t - timedelta(days=t.weekday())).isoformat()
    sources = list(JOB_CALENDAR_PATTERNS)
    live = [s for s in shifts if s["shift_date"] >= cutoff]
    with _conn() as conn:
        conn.executemany(
            """INSERT INTO earnings_scheduled_shifts
                   (source, shift_date, calendar_event_id, summary, start_at, end_at,
                    roster_source)
               VALUES (:source, :shift_date, :calendar_event_id, :summary,
                       :start_at, :end_at, :roster_source)
               ON CONFLICT (source, shift_date) DO UPDATE SET
                   calendar_event_id = excluded.calendar_event_id,
                   summary           = excluded.summary,
                   start_at          = excluded.start_at,
                   end_at            = excluded.end_at,
                   roster_source     = excluded.roster_source,
                   synced            = datetime('now')""",
            live,
        )
        keep = {(s["source"], s["shift_date"]) for s in live}
        stale = [
            r["id"] for r in conn.execute(
                "SELECT id, source, shift_date FROM earnings_scheduled_shifts "
                "WHERE shift_date >= ? AND source IN (%s)"
                % ",".join("?" * len(sources)), [cutoff, *sources])
            if (r["source"], r["shift_date"]) not in keep
        ]
        if stale:
            conn.executemany(
                "DELETE FROM earnings_scheduled_shifts WHERE id=?",
                [(i,) for i in stale])
        return conn.total_changes


def forecast(months: int = 6) -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT * FROM earnings_expected_month_total
               WHERE month >= strftime('%Y-%m', 'now') ORDER BY month LIMIT ?""",
            (months,)).fetchall()]


def forecast_by_source() -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT * FROM earnings_expected_month
               WHERE month >= strftime('%Y-%m', 'now') ORDER BY month, source""").fetchall()]


def _print_forecast() -> None:
    with _conn() as conn:
        print("Historical average per shift, by job and day of week:")
        names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        for r in conn.execute("SELECT * FROM earnings_dow_avg ORDER BY source, dow"):
            print(f"  {r['source']:<18} {names[r['dow']]}  ${r['avg_shift_total']:>7.2f}"
                  f"  ({r['sample_shifts']} shifts, {r['first_shift']} to {r['last_shift']})")
        for r in conn.execute("SELECT * FROM earnings_source_avg"):
            print(f"  {r['source']:<18} any  ${r['avg_shift_total']:>7.2f}"
                  f"  ({r['sample_shifts']} shifts)  <- fallback for a day with no history")

    print("\nExpected earnings per month:")
    for row in forecast_by_source():
        flag = f"  ({row['shifts_priced_by_fallback']} priced by fallback)" if row["shifts_priced_by_fallback"] else ""
        print(f"  {row['month']}  {row['source']:<18} {row['scheduled_shifts']:>2} shifts"
              f"  ${row['expected_total']:>8.2f}{flag}")
    print("  " + "-" * 56)
    for row in forecast():
        print(f"  {row['month']}  {'ALL JOBS':<18} {row['scheduled_shifts']:>2} shifts"
              f"  ${row['expected_total']:>8.2f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--show", action="store_true", help="print the forecast without syncing")
    ap.add_argument("--months", type=int, default=6, help="how far ahead to read the calendar")
    ap.add_argument("--no-audit", action="store_true", help="skip the Haiku missed-shift check")
    ap.add_argument("--force-audit", action="store_true",
                    help="re-run the check even if the calendar has not changed")
    args = ap.parse_args()

    if not args.show:
        print(f"SpotOn mirror: {mirror_spoton()}")
        events = list_events(args.months)
        shifts = fetch_shifts(events=events)
        replace_scheduled(shifts)
        print(f"Synced {len(shifts)} scheduled shift(s) from calendar.")
        if not args.no_audit:
            a = audit(events, shifts, force=args.force_audit)
            if a.get("error"):
                print(f"Missed-shift check did not run: {a['error']}")
            elif a.get("missed"):
                print(f"Haiku flags {len(a['missed'])} event(s) as shifts the sync did not pick up:")
                for m in a["missed"]:
                    print(f"  {m['date']}  {m['summary']}")
            else:
                print("Missed-shift check: none.")
        print()
    _print_forecast()


if __name__ == "__main__":
    main()
