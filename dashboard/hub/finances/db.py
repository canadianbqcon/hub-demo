# vault-code/dashboard/hub/finances/db.py
"""Earnings data layer for the Hub finances module.

Generic, source-keyed: one `earnings` parent row per income event/period, with
optional `earnings_shifts` and `earnings_deductions` children. Money is REAL;
every sum rounds to cents. Mirrors the connection pattern used across the Hub
modules (purchases/db.py).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from sqlite_helpers import connect as sqlite_connect, row as _row, rows as _rows

_db_path: Path | None = None

_PARENT_COLS = [
    "source", "source_type", "period_start", "period_end", "granularity",
    "gross", "net", "hours", "wages", "cash_tips", "cc_tips_gross",
    "cc_tips_net", "tax_withheld",
    "source_doc", "notes",
]
_SHIFT_COLS = [
    "shift_date", "clock_in", "clock_out", "hours", "rate", "tipped",
    "wage_pay", "cash_tips", "cc_tips_gross", "cc_tips_net", "shift_total",
    "note",
]
_DEDUCTION_COLS = ["label", "amount", "ytd_amount"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS earnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    source_type   TEXT NOT NULL,
    period_start  TEXT NOT NULL,
    period_end    TEXT NOT NULL,
    granularity   TEXT NOT NULL DEFAULT 'pay_period',
    gross         REAL,
    net           REAL,
    hours         REAL,
    wages         REAL,
    cash_tips     REAL,
    cc_tips_gross REAL,
    cc_tips_net   REAL,
    tax_withheld  REAL,
    source_doc    TEXT,
    notes         TEXT NOT NULL DEFAULT '',
    created       TEXT NOT NULL DEFAULT (datetime('now')),
    updated       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, period_start, period_end)
) STRICT;

CREATE TABLE IF NOT EXISTS earnings_shifts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    earnings_id   INTEGER NOT NULL REFERENCES earnings(id) ON DELETE CASCADE,
    shift_date    TEXT NOT NULL,
    clock_in      TEXT,
    clock_out     TEXT,
    hours         REAL,
    rate          REAL,
    tipped        INTEGER NOT NULL DEFAULT 0,
    wage_pay      REAL,
    cash_tips     REAL,
    cc_tips_gross REAL,
    cc_tips_net   REAL,
    shift_total   REAL,
    note          TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_earnings_shifts_parent ON earnings_shifts(earnings_id);

CREATE TABLE IF NOT EXISTS earnings_deductions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    earnings_id INTEGER NOT NULL REFERENCES earnings(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    amount      REAL,
    ytd_amount  REAL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_earnings_deductions_parent ON earnings_deductions(earnings_id);

-- Forecast side (migration 003). Upcoming shifts read off Google Calendar by
-- finances/shift_calendar.py, priced at the historical average for that job and
-- day of week. Kept out of the `earnings` table so actuals stay actuals.
CREATE TABLE IF NOT EXISTS earnings_scheduled_shifts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT NOT NULL,
    shift_date        TEXT NOT NULL,
    calendar_event_id TEXT,
    summary           TEXT,
    synced            TEXT NOT NULL DEFAULT (datetime('now')),
    -- Pricing model (migration 005). The window is what lets a 9pm-3am Friday
    -- price differently from a 4:30pm-3am one; model_* is shift_pricing.py's
    -- answer written back, and stays NULL when a row is unpriced so the view
    -- falls through to the day-of-week average.
    start_at          TEXT,    -- 'HH:MM' local
    end_at            TEXT,    -- 'HH:MM'; <= start_at means it crosses midnight
    role              TEXT,
    shift_kind        TEXT,    -- 'regular' | 'buyout'
    -- Provenance (migration 006). 'posted' = read off a SpotOn roster, 'assumed'
    -- = projected from a recurring pattern. Derived from the calendar event's
    -- description at sync time. Nullable with no default on purpose: NULL means
    -- "not determined yet" and renders as nothing, the pre-006 behaviour.
    roster_source     TEXT,
    model_hours       REAL,
    model_wages       REAL,
    model_tips        REAL,
    model_total       REAL,
    model_share       REAL,    -- mean points share across worked hours
    priced_at         TEXT,
    pricing_note      TEXT,
    UNIQUE (source, shift_date)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_earnings_scheduled_date ON earnings_scheduled_shifts(shift_date);

-- One row per worked day. A shift can span two earnings_shifts rows when a
-- paycheck error is rectified a period later; averaging raw rows would read
-- that as two half-price shifts.
CREATE VIEW IF NOT EXISTS earnings_shift_days AS
SELECT e.source                                      AS source,
       s.shift_date                                  AS shift_date,
       CAST(strftime('%w', s.shift_date) AS INTEGER) AS dow,
       SUM(s.shift_total)                            AS shift_total,
       SUM(s.hours)                                  AS hours
FROM earnings_shifts s
JOIN earnings e ON e.id = s.earnings_id
WHERE s.shift_total IS NOT NULL
GROUP BY e.source, s.shift_date;

-- Averages count a tipped source only from its first tipped shift (migration 008).
CREATE VIEW IF NOT EXISTS earnings_shift_days_priced AS
SELECT d.*
FROM earnings_shift_days d
WHERE d.shift_date >= COALESCE(
        (SELECT MIN(s.shift_date)
           FROM earnings_shifts s JOIN earnings e ON e.id = s.earnings_id
          WHERE s.tipped = 1 AND e.source = d.source), '');

CREATE VIEW IF NOT EXISTS earnings_dow_avg AS
SELECT source, dow,
       COUNT(*)                   AS sample_shifts,
       ROUND(AVG(shift_total), 2) AS avg_shift_total,
       ROUND(AVG(hours), 2)       AS avg_hours,
       MIN(shift_date)            AS first_shift,
       MAX(shift_date)            AS last_shift
FROM earnings_shift_days_priced
GROUP BY source, dow;

CREATE VIEW IF NOT EXISTS earnings_source_avg AS
SELECT source,
       COUNT(*)                   AS sample_shifts,
       ROUND(AVG(shift_total), 2) AS avg_shift_total,
       ROUND(AVG(hours), 2)       AS avg_hours
FROM earnings_shift_days_priced
GROUP BY source;

-- Claim terms (migration 004). One row per claim; a new benefit year is a new row.
CREATE TABLE IF NOT EXISTS earnings_ui_claim (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL UNIQUE,
    effective_date   TEXT NOT NULL,
    benefit_year_end TEXT NOT NULL,
    weekly_rate      REAL NOT NULL,
    days_per_week    INTEGER NOT NULL DEFAULT 4,
    max_payable      REAL NOT NULL,
    withholding_rate REAL,
    notes            TEXT NOT NULL DEFAULT ''
) STRICT;

-- Pricing model (migration 005). Tip-pool points by role, assessed PER HOUR:
-- two barbacks in the same hour each take half the barback share for that hour.
-- `verified` separates what Sam confirmed from what the model assumes, so
-- the UI can label a guess instead of passing it off as measured.
CREATE TABLE IF NOT EXISTS earnings_tip_points (
    source   TEXT NOT NULL,
    role     TEXT NOT NULL,
    points   REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    note     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source, role)
) STRICT;

-- Hourly pool densities and the wage rate. Densities are back-solved from paid
-- shifts by shift_pricing.calibrate(), never hand-picked.
CREATE TABLE IF NOT EXISTS earnings_pricing_params (
    source   TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    note     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source, key)
) STRICT;

-- Everyone else sharing the pool that night. end_at <= start_at crosses midnight.
CREATE TABLE IF NOT EXISTS earnings_shift_crew (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id INTEGER NOT NULL REFERENCES earnings_scheduled_shifts(id) ON DELETE CASCADE,
    role     TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at   TEXT NOT NULL,
    label    TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE INDEX IF NOT EXISTS idx_earnings_shift_crew_shift ON earnings_shift_crew(shift_id);

-- The model price wins when present. Below it, a row that carries its own
-- start_at/end_at is priced on ITS hours at the day's average pay PER HOUR --
-- never at the flat per-shift day-of-week mean, which read a 10.5-hour Friday
-- as the 6.1-hour average of eight past Fridays (migration 007). The flat mean
-- survives only for a row with no window at all. `priced_by` says which rung
-- produced the number, so an estimate is never shown as a modelled figure.
CREATE VIEW IF NOT EXISTS earnings_expected_shift AS
SELECT sch.source                                            AS source,
       sch.shift_date                                        AS shift_date,
       CAST(strftime('%w', sch.shift_date) AS INTEGER)       AS dow,
       strftime('%Y-%m', sch.shift_date)                     AS month,
       DATE(sch.shift_date, '+' || ((7 - CAST(strftime('%w', sch.shift_date) AS INTEGER)) % 7) || ' days')
                                                             AS week_end,
       sch.start_at                                          AS start_at,
       sch.end_at                                            AS end_at,
       sch.role                                              AS role,
       sch.shift_kind                                        AS shift_kind,
       sch.roster_source                                     AS roster_source,
       sch.model_share                                       AS model_share,
       sch.pricing_note                                      AS pricing_note,
       COALESCE(sch.model_total,
                ROUND(sch.window_hours * (d.avg_shift_total / NULLIF(d.avg_hours, 0)), 2),
                ROUND(sch.window_hours * (o.avg_shift_total / NULLIF(o.avg_hours, 0)), 2),
                d.avg_shift_total, o.avg_shift_total)        AS expected_total,
       COALESCE(sch.model_hours, sch.window_hours,
                d.avg_hours, o.avg_hours)                    AS expected_hours,
       sch.model_wages                                       AS expected_wages,
       sch.model_tips                                        AS expected_tips,
       COALESCE(d.sample_shifts, 0)                          AS dow_sample_shifts,
       CASE WHEN sch.model_total IS NOT NULL THEN 'model'
            WHEN sch.window_hours IS NOT NULL AND d.avg_hours > 0 THEN 'dow_rate'
            WHEN sch.window_hours IS NOT NULL AND o.avg_hours > 0 THEN 'source_rate'
            WHEN d.avg_shift_total IS NOT NULL THEN 'dow'
            ELSE 'fallback' END                              AS priced_by,
       CASE WHEN sch.model_total IS NULL
             AND NOT (sch.window_hours IS NOT NULL AND d.avg_hours > 0)
             AND d.avg_shift_total IS NULL
            THEN 1 ELSE 0 END                                AS used_fallback
-- window_hours is computed once here so the HH:MM arithmetic is not repeated in
-- three places above. (end - start + 1440) % 1440 carries a shift crossing
-- midnight into the next day, matching shift_pricing.span().
-- ponytail: end == start reads as 0 hours, not 24. No such row exists and a
-- zero is the safe way to be wrong.
FROM (SELECT *,
             CASE WHEN start_at IS NOT NULL AND end_at IS NOT NULL THEN
                 ((  (CAST(substr(end_at, 1, 2) AS INTEGER) * 60
                    + CAST(substr(end_at, 4, 2) AS INTEGER))
                   - (CAST(substr(start_at, 1, 2) AS INTEGER) * 60
                    + CAST(substr(start_at, 4, 2) AS INTEGER))
                   + 1440) % 1440) / 60.0
             END AS window_hours
      FROM earnings_scheduled_shifts) sch
LEFT JOIN earnings_dow_avg d
       ON d.source = sch.source
      AND d.dow = CAST(strftime('%w', sch.shift_date) AS INTEGER)
LEFT JOIN earnings_source_avg o
       ON o.source = sch.source;

CREATE VIEW IF NOT EXISTS earnings_expected_month AS
SELECT month, source,
       COUNT(*)                      AS scheduled_shifts,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback)            AS shifts_priced_by_fallback,
       SUM(CASE WHEN priced_by = 'model' THEN 1 ELSE 0 END)      AS shifts_priced_by_model,
       SUM(CASE WHEN roster_source = 'assumed' THEN 1 ELSE 0 END) AS shifts_assumed,
       ROUND(SUM(CASE WHEN roster_source = 'assumed' THEN expected_total ELSE 0 END), 2)
                                                                 AS assumed_total
FROM earnings_expected_shift
GROUP BY month, source;

CREATE VIEW IF NOT EXISTS earnings_expected_month_total AS
SELECT month,
       COUNT(*)                      AS scheduled_shifts,
       COUNT(DISTINCT source)        AS jobs,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback)            AS shifts_priced_by_fallback,
       SUM(CASE WHEN priced_by = 'model' THEN 1 ELSE 0 END)      AS shifts_priced_by_model,
       SUM(CASE WHEN roster_source = 'assumed' THEN 1 ELSE 0 END) AS shifts_assumed,
       ROUND(SUM(CASE WHEN roster_source = 'assumed' THEN expected_total ELSE 0 END), 2)
                                                                 AS assumed_total
FROM earnings_expected_shift
GROUP BY month;

-- Predicted hours per benefit week across every job -- NYSDOL counts total hours
-- worked in the week, not per employer, capping each calendar day at 10.
CREATE VIEW IF NOT EXISTS earnings_expected_week_hours AS
SELECT week_end,
       ROUND(SUM(capped_hours), 2) AS hours,
       COUNT(*)                    AS shifts
FROM (SELECT week_end, shift_date, MIN(SUM(expected_hours), 10.0) AS capped_hours
      FROM earnings_expected_shift
      GROUP BY week_end, shift_date)
GROUP BY week_end;
"""


def init(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def _conn():
    return sqlite_connect(_db_path, "finances.db")




def upsert_earning(record: dict, shifts: list[dict],
                   deductions: list[dict] | None = None) -> int:
    """Insert or update (on the UNIQUE period key) one earnings row + children.

    tax_withheld is taken verbatim from record; no computation here.
    deductions is a list of {label, amount, ytd_amount} dicts from the stub.
    """
    values = {c: record.get(c) for c in _PARENT_COLS}
    # Mirror NOT NULL column defaults: INSERT binds every column explicitly so
    # SQLite's DEFAULT never fires; replicate them here instead.
    values["granularity"] = values["granularity"] or "pay_period"
    values["notes"] = values["notes"] if values["notes"] is not None else ""

    with _conn() as conn:
        existing = conn.execute(
            "SELECT id FROM earnings WHERE source=? AND period_start=? AND period_end=?",
            (values["source"], values["period_start"], values["period_end"]),
        ).fetchone()
        if existing:
            eid = existing["id"]
            sets = ", ".join(f"{c}=:{c}" for c in _PARENT_COLS)
            conn.execute(
                f"UPDATE earnings SET {sets}, updated=datetime('now') WHERE id=:id",
                {**values, "id": eid},
            )
            conn.execute("DELETE FROM earnings_shifts WHERE earnings_id=?", (eid,))
            conn.execute("DELETE FROM earnings_deductions WHERE earnings_id=?", (eid,))
        else:
            cols = ", ".join(_PARENT_COLS)
            ph = ", ".join(f":{c}" for c in _PARENT_COLS)
            cur = conn.execute(f"INSERT INTO earnings ({cols}) VALUES ({ph})", values)
            eid = cur.lastrowid
            assert eid is not None  # AUTOINCREMENT INSERT always yields a rowid

        for s in shifts:
            sv = {c: s.get(c) for c in _SHIFT_COLS}
            sv["earnings_id"] = eid
            cols = "earnings_id, " + ", ".join(_SHIFT_COLS)
            ph = ":earnings_id, " + ", ".join(f":{c}" for c in _SHIFT_COLS)
            conn.execute(f"INSERT INTO earnings_shifts ({cols}) VALUES ({ph})", sv)

        for d in (deductions or []):
            dv = {c: d.get(c) for c in _DEDUCTION_COLS}
            dv["earnings_id"] = eid
            cols = "earnings_id, " + ", ".join(_DEDUCTION_COLS)
            ph = ":earnings_id, " + ", ".join(f":{c}" for c in _DEDUCTION_COLS)
            conn.execute(f"INSERT INTO earnings_deductions ({cols}) VALUES ({ph})", dv)

    return eid


def list_earnings() -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT * FROM earnings ORDER BY period_end DESC, id DESC").fetchall())


def get_earning(earning_id: int) -> dict | None:
    with _conn() as conn:
        parent = _row(conn.execute(
            "SELECT * FROM earnings WHERE id=?", (earning_id,)).fetchone())
        if parent is None:
            return None
        parent["shifts"] = _rows(conn.execute(
            "SELECT * FROM earnings_shifts WHERE earnings_id=? ORDER BY shift_date DESC, id DESC",
            (earning_id,)).fetchall())
        parent["deductions"] = _rows(conn.execute(
            "SELECT * FROM earnings_deductions WHERE earnings_id=? ORDER BY id",
            (earning_id,)).fetchall())
        return parent


def _scope_bounds(scope: str, today: str) -> tuple[str, str]:
    # Rolling, not calendar (his mark 2026-11-03): on a Tuesday the week runs from
    # last Tuesday to today, and the month from this date last month.
    d = date.fromisoformat(today)
    if scope == "week":
        return (d - timedelta(days=7)).isoformat(), d.isoformat()
    if scope == "month":
        from .budget import _add_months  # budget imports db at module load
        return _add_months(today, -1), d.isoformat()
    if scope == "ytd":
        return d.replace(month=1, day=1).isoformat(), d.isoformat()
    raise ValueError(f"unknown scope: {scope}")


def totals(scope: str, today: str) -> dict:
    lo, hi = _scope_bounds(scope, today)
    with _conn() as conn:
        r = conn.execute(
            "SELECT "
            " COALESCE(SUM(gross),0) AS gross, COALESCE(SUM(net),0) AS net, "
            " COALESCE(SUM(hours),0) AS hours, COALESCE(SUM(wages),0) AS wages, "
            " COALESCE(SUM(cash_tips),0) AS cash_tips, "
            " COALESCE(SUM(cc_tips_net),0) AS cc_tips_net, "
            " COALESCE(SUM(tax_withheld),0) AS tax_withheld "
            "FROM earnings WHERE period_end >= ? AND period_end <= ?",
            (lo, hi),
        ).fetchone()
    hours = round(r["hours"], 2)
    gross = round(r["gross"], 2)
    return {
        "gross": gross,
        "net": round(r["net"], 2),
        "hours": hours,
        "cash_tips": round(r["cash_tips"], 2),
        "cc_tips_net": round(r["cc_tips_net"], 2),
        "withheld": round(r["tax_withheld"], 2),
        "effective_hourly": round(gross / hours, 2) if hours else 0.0,
    }


def by_source() -> list[dict]:
    with _conn() as conn:
        rows = _rows(conn.execute(
            "SELECT source, "
            " COALESCE(SUM(gross),0) AS gross, "
            " COALESCE(SUM(net),0) AS net, "
            " COALESCE(SUM(hours),0) AS hours, "
            " COALESCE(SUM(tax_withheld),0) AS tax "
            "FROM earnings GROUP BY source ORDER BY gross DESC").fetchall())
    # round in Python (not SQL ROUND) so this matches totals()' rounding mode
    return [
        {**r, "gross": round(r["gross"], 2), "net": round(r["net"], 2),
         "hours": round(r["hours"], 2), "tax": round(r["tax"], 2)}
        for r in rows
    ]


# NYSDOL prices a benefit week off total hours worked, not days scheduled. Each
# calendar day counts at most 10 hours. Ceiling -> days of work reported; effective
# days are 4 minus that, and each effective day pays a quarter of the weekly rate.
# https://dol.ny.gov/unemployment/partial-unemployment-eligibility
_HOURS_TO_WORK_DAYS = [(10, 0), (16, 1), (21, 2), (30, 3)]


def work_days_for_hours(hours: float) -> int:
    """Days of work NYSDOL charges for a week of `hours`. 31+ kills the week."""
    reported = round(hours)          # he certifies whole hours
    for ceiling, days in _HOURS_TO_WORK_DAYS:
        if reported <= ceiling:
            return days
    return 4


def ui_forecast(today: str | None = None, assume_shifts: int = 0,
                through: str | None = None) -> dict:
    """Predicted unemployment benefit, week by week, from predicted shift hours.

    By default only weeks up to the last scheduled shift are forecast. Past that
    the calendar is empty because nothing is *rostered* yet, not because he is
    off -- assuming zero hours there would invent full-rate weeks that will not
    happen.

    `assume_shifts` is the other half of that: a week the calendar says nothing
    about gets filled at that cadence, priced off the job's average shift, and
    runs out to `through`. A week that already holds even one rostered shift is
    left exactly as rostered -- one shift is information, not a blank. Weeks
    filled this way carry `assumed: True` so callers can label them.

    Effective days remaining come from the money ceiling (max_payable minus what
    has been paid), never a hand-maintained counter, so the forecast stops paying
    the moment the claim is exhausted.
    """
    today = today or date.today().isoformat()
    with _conn() as conn:
        claim = _row(conn.execute("SELECT * FROM earnings_ui_claim LIMIT 1").fetchone())
        if not claim:
            return {"weeks": [], "by_month": {}, "claim": None}
        paid = conn.execute(
            "SELECT COALESCE(SUM(gross), 0) FROM earnings WHERE source = ?",
            (claim["source"],)).fetchone()[0]
        hours_by_week = {r["week_end"]: r for r in _rows(conn.execute(
            "SELECT w.week_end, w.hours, w.shifts, s.total AS shift_total "
            "FROM earnings_expected_week_hours w JOIN ("
            "  SELECT week_end, ROUND(SUM(expected_total), 2) AS total "
            "  FROM earnings_expected_shift GROUP BY week_end) s "
            "ON s.week_end = w.week_end ORDER BY w.week_end").fetchall())}
        # The job he actually works most is what an unrostered week gets priced at.
        base = _row(conn.execute(
            "SELECT avg_shift_total, avg_hours FROM earnings_source_avg "
            "ORDER BY sample_shifts DESC LIMIT 1").fetchone()) or {}

    day_rate = claim["weekly_rate"] / claim["days_per_week"]
    days_left = int((claim["max_payable"] - paid) / day_rate)
    keep = 1.0 - (claim["withholding_rate"] or 0.0)

    # First unstarted benefit week, then forward to the last week holding a shift
    # -- or to `through`, when empty weeks are being filled in.
    start = date.fromisoformat(today)
    start += timedelta(days=(6 - start.weekday()))        # this week's Sunday
    last = max(hours_by_week) if hours_by_week else None
    bye = claim["benefit_year_end"]
    legacy = assume_shifts <= 0 and through is None
    end = (min(last, bye) if last else None) if legacy else (through or last)

    weeks, cursor = [], start
    while end and cursor.isoformat() <= end:
        wk = cursor.isoformat()
        row = hours_by_week.get(wk)
        assumed = row is None and assume_shifts > 0
        if row:
            hours, shifts = row["hours"], row["shifts"]
            shift_total = row["shift_total"] or 0.0
        elif assumed:
            shifts = assume_shifts
            hours = round(min(assume_shifts * (base.get("avg_hours") or 0.0), 70.0), 2)
            shift_total = round(assume_shifts * (base.get("avg_shift_total") or 0.0), 2)
        else:
            hours, shifts, shift_total = 0.0, 0, 0.0
        # Past the benefit year or past the money ceiling, the week still exists
        # (he still works it) -- it just pays nothing.
        if wk <= bye and days_left > 0:
            earned = claim["days_per_week"] - work_days_for_hours(hours)
            paid_days = min(earned, days_left)
            days_left -= paid_days
        else:
            earned = paid_days = 0
        weeks.append({
            "week_end": wk,
            "month": wk[:7],
            "hours": round(hours, 2),
            "shifts": shifts,
            "shift_total": round(shift_total, 2),
            "assumed": assumed,
            "effective_days": paid_days,
            "capped_by_claim": paid_days < earned,
            "gross": round(paid_days * day_rate, 2),
            "net": round(paid_days * day_rate * keep, 2),
        })
        cursor += timedelta(days=7)
        if legacy and days_left <= 0:
            break

    by_month: dict[str, dict] = {}
    for w in weeks:
        m = by_month.setdefault(w["month"], {"weeks": 0, "gross": 0.0, "net": 0.0,
                                             "effective_days": 0, "shifts": 0,
                                             "shift_total": 0.0, "assumed_weeks": 0})
        m["weeks"] += 1
        m["gross"] = round(m["gross"] + w["gross"], 2)
        m["net"] = round(m["net"] + w["net"], 2)
        m["effective_days"] += w["effective_days"]
        m["shifts"] += w["shifts"]
        m["shift_total"] = round(m["shift_total"] + w["shift_total"], 2)
        m["assumed_weeks"] += 1 if w["assumed"] else 0
    return {
        "weeks": weeks,
        "by_month": by_month,
        "claim": {**claim, "paid_to_date": round(paid, 2),
                  "days_remaining": int((claim["max_payable"] - paid) / day_rate),
                  "days_after_forecast": days_left,
                  "day_rate": round(day_rate, 2),
                  "horizon": last},
    }


def withholding_ratio(source: str) -> float:
    """Net as a fraction of gross, from this job's own paid checks.

    Derived, never assumed: a hardcoded 0.84 would silently rot the moment his
    withholding changes. Falls back to 1.0 (show gross) rather than inventing a
    rate when there is nothing to measure.
    """
    with _conn() as conn:
        r = conn.execute(
            "SELECT COALESCE(SUM(gross),0) g, COALESCE(SUM(net),0) n "
            "FROM earnings WHERE source=? AND gross > 0", (source,)).fetchone()
    return round(r["n"] / r["g"], 4) if r and r["g"] else 1.0


# Payroll runs Monday-Sunday and the check lands the following Thursday.
_PAYDAY_OFFSET = 4          # days after the Sunday the week ends on


def pay_calendar(today: str | None = None, source: str = "juniper-and-co") -> dict:
    """Forecast regrouped the way he actually receives it: as paychecks.

    A month total is not what hits his account -- a Mon-Sun week does, four days
    later. This joins each benefit week's shifts to the unemployment those same
    hours earn, because the two move in opposite directions: a heavy week earns
    more in shifts and less in UI, and only the combined figure is the answer to
    "what am I getting paid".
    """
    today = today or date.today().isoformat()
    keep = withholding_ratio(source)
    ui = ui_forecast(today)
    ui_by_week = {w["week_end"]: w for w in ui["weeks"]}

    # A paycheck carries its whole Mon-Sun week, worked days included: filter by
    # whether the check has landed yet, not by whether each shift is past.
    first_week_end = (date.fromisoformat(today) - timedelta(days=_PAYDAY_OFFSET)).isoformat()
    with _conn() as conn:
        rows = _rows(conn.execute(
            "SELECT * FROM earnings_expected_shift WHERE source=? AND week_end >= ? "
            "ORDER BY shift_date", (source, first_week_end)).fetchall())

    weeks: dict[str, dict] = {}
    for r in rows:
        w = weeks.setdefault(r["week_end"], {
            "week_end": r["week_end"],
            "week_start": (date.fromisoformat(r["week_end"]) - timedelta(days=6)).isoformat(),
            "pay_date": (date.fromisoformat(r["week_end"])
                         + timedelta(days=_PAYDAY_OFFSET)).isoformat(),
            "shifts": [], "shift_gross": 0.0, "hours": 0.0,
        })
        w["shifts"].append(r)
        w["shift_gross"] = round(w["shift_gross"] + (r["expected_total"] or 0.0), 2)
        w["hours"] = round(w["hours"] + (r["expected_hours"] or 0.0), 2)

    out = []
    for wk in sorted(weeks.values(), key=lambda x: x["week_end"]):
        u = ui_by_week.get(wk["week_end"]) or {}
        wk["shift_net"] = round(wk["shift_gross"] * keep, 2)
        wk["ui_gross"] = u.get("gross", 0.0)
        wk["ui_net"] = u.get("net", 0.0)
        wk["ui_effective_days"] = u.get("effective_days", 0)
        wk["total_gross"] = round(wk["shift_gross"] + wk["ui_gross"], 2)
        wk["total_net"] = round(wk["shift_net"] + wk["ui_net"], 2)
        out.append(wk)
    return {"weeks": out, "withholding_ratio": keep,
            "payday_offset_days": _PAYDAY_OFFSET,
            "claim": ui["claim"]}


def expected(months: int = 4, today: str | None = None) -> dict:
    """Forecast: scheduled shifts priced at the historical day-of-week average.

    Months run from the current one forward. `dow_avg` rides along so the page
    can show what each figure is built from -- a day of week with no history is
    priced at the job's overall average and flagged, not silently guessed.
    """
    month_from = (today or date.today().isoformat())[:7]
    with _conn() as conn:
        rows = _rows(conn.execute(
            "SELECT * FROM earnings_expected_month_total "
            "WHERE month >= ? ORDER BY month LIMIT ?", (month_from, months)).fetchall())
        by_src = _rows(conn.execute(
            "SELECT * FROM earnings_expected_month "
            "WHERE month >= ? ORDER BY month, expected_total DESC", (month_from,)).fetchall())
        dow = _rows(conn.execute(
            "SELECT * FROM earnings_dow_avg ORDER BY source, dow").fetchall())
        fallback = _rows(conn.execute(
            "SELECT * FROM earnings_source_avg ORDER BY source").fetchall())
    ui = ui_forecast(today)
    months_seen = {r["month"] for r in rows}
    for r in rows:
        r["sources"] = [s for s in by_src if s["month"] == r["month"]]
        r["shift_total"] = r["expected_total"]
        r["ui"] = ui["by_month"].get(r["month"])
        r["expected_total"] = round(r["shift_total"] + (r["ui"]["gross"] if r["ui"] else 0.0), 2)
    # A month can hold UI weeks but no shifts (he is rostered nowhere that month);
    # it still earns money, so it gets a row rather than silently vanishing.
    for m, u in sorted(ui["by_month"].items()):
        if m in months_seen or m < month_from:
            continue
        rows.append({"month": m, "scheduled_shifts": 0, "jobs": 0, "sources": [],
                     "shift_total": 0.0, "shifts_priced_by_fallback": 0,
                     "ui": u, "expected_total": u["gross"]})
    rows.sort(key=lambda r: r["month"])
    # The sync's own report on itself. A month whose shift count is wrong because
    # the calendar matcher went blind looks identical to a month he simply is not
    # rostered for, so the page has to be told the difference rather than infer it.
    from finances.shift_calendar import read_audit  # absolute: tests and scripts load db.py outside the package
    return {"months": rows[:months], "dow_avg": dow, "fallback_avg": fallback,
            "ui_claim": ui["claim"], "ui_weeks": ui["weeks"],
            "pay": pay_calendar(today), "sync_audit": read_audit()}
