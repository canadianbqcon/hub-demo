"""Per-day briefing snapshot store (table `briefing_day` in tasks.db).

Freezes the parts of a day's briefing that are derived from live state — the
weather forecast and the weather/situation-derived bring + prep items — so that
looking back at a past day shows what was true then instead of "no forecast" and
an empty bring list. Event-authored bring already persists via the calendar
event's description; this captures the bits that would otherwise vanish on
rollover.

Write rule: only the server's current local day is ever written (`save_today`).
Past days are never touched here, so once a day rolls over its row is frozen — a
durable record. The five forecast fields and bring/prep are kept forever; the
full day detail in `wx` (hourly row, wind, uv, sun, humidity) is kept WX_DAYS
days and cleared after (2026-11-03 mark: store a month). `backfill`
seeds forecast-only rows for past days that have none yet (one-time archive seed)
and likewise never overwrites an existing row.
"""

import json
import sqlite3
from datetime import date, timedelta

import tasks  # reuse tasks.db location (DB_PATH); the table lives there

WX_DAYS = 31
_WX_KEYS = ("feels", "wind", "uv", "sunrise", "sunset", "hum", "hours")


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(str(tasks.DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def _row_to_entry(r: sqlite3.Row) -> dict:
    wx = json.loads(r["wx"]) if "wx" in r.keys() and r["wx"] else {}
    return {
        **wx,
        "temp": r["temp"],
        "code": r["code"],
        "hi": r["hi"],
        "lo": r["lo"],
        "precip": r["precip"],
        "bring": json.loads(r["bring"] or "[]"),
        "prep": json.loads(r["prep"] or "[]"),
    }


def get_all() -> dict:
    """Every stored snapshot, keyed by date → {temp,code,hi,lo,precip,bring,prep}."""
    con = _con()
    try:
        rows = con.execute("SELECT * FROM briefing_day").fetchall()
        return {r["date"]: _row_to_entry(r) for r in rows}
    finally:
        con.close()


def save_today(forecast: dict | None, bring: list | None, prep: list | None) -> str:
    """Upsert the snapshot for the SERVER's current local day only. The client may
    send any date it likes; we ignore it and key on server-today, so a stale tab
    can never rewrite a past (frozen) day. Returns the date written."""
    today = date.today().isoformat()
    f = forecast or {}
    wx = {k: f[k] for k in _WX_KEYS if f.get(k) is not None}
    con = _con()
    try:
        con.execute(
            """
            INSERT INTO briefing_day
                (date, temp, code, hi, lo, precip, bring, prep, wx, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(date) DO UPDATE SET
                temp=excluded.temp, code=excluded.code, hi=excluded.hi,
                lo=excluded.lo, precip=excluded.precip,
                bring=excluded.bring, prep=excluded.prep,
                wx=COALESCE(excluded.wx, briefing_day.wx),
                updated_at=datetime('now')
            """,
            (
                today,
                f.get("temp"),
                f.get("code"),
                f.get("hi"),
                f.get("lo"),
                f.get("precip"),
                json.dumps(bring or []),
                json.dumps(prep or []),
                json.dumps(wx) if wx else None,
            ),
        )
        cutoff = (date.today() - timedelta(days=WX_DAYS)).isoformat()
        con.execute("UPDATE briefing_day SET wx=NULL WHERE date < ? AND wx IS NOT NULL", (cutoff,))
        con.commit()
    finally:
        con.close()
    return today


def backfill(by_date: dict | None) -> int:
    """One-time archive seed: insert a forecast-only row for each PAST day in
    `by_date` ({date: {temp,code,hi,lo,precip}}) that has no row yet. Never
    overwrites. Returns the number of rows inserted."""
    today = date.today().isoformat()
    con = _con()
    n = 0
    try:
        for d, f in (by_date or {}).items():
            if d >= today:
                continue  # only seed the past; today/future write live
            if con.execute("SELECT 1 FROM briefing_day WHERE date=?", (d,)).fetchone():
                continue  # never overwrite an existing (possibly richer) row
            con.execute(
                "INSERT INTO briefing_day (date, temp, code, hi, lo, precip) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (d, f.get("temp"), f.get("code"), f.get("hi"), f.get("lo"), f.get("precip")),
            )
            n += 1
        con.commit()
    finally:
        con.close()
    return n
