"""Read helper for data/cards.db — per-card payment-due metadata.

YNAB's API does not expose payment due dates (dashboard/ynab.py::fetch_credit_cards
returns due="" for every card). This module holds the manually-curated due days and
merges them over the live YNAB fetch so the Hub home shows "due jun 14" style
strings. Stored value is a recurring day-of-month; enrich() computes the next
occurrence relative to today.

Read-only from the app's perspective — rows are managed by data/seed_cards.py.
"""

import sqlite3
import sys
from datetime import date
from pathlib import Path

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(
        0, str(Path(__file__).resolve().parent.parent)
    )  # dashboard/, for vault_path
from vault_path import vault_root

_DB = vault_root() / "data" / "cards.db"

_PRAGMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA temp_store   = MEMORY;
"""


def _connect():
    conn = sqlite3.connect(_DB)
    conn.executescript(_PRAGMA)
    conn.row_factory = sqlite3.Row
    return conn


def _rows() -> dict[str, sqlite3.Row]:
    """Return {lowercased card name: row}. Empty if the DB is missing."""
    if not _DB.exists():
        return {}
    conn = _connect()
    try:
        rows = conn.execute("SELECT name, due_day, last4 FROM card").fetchall()
    finally:
        conn.close()
    return {r["name"].lower(): r for r in rows}



def _next_occurrence(today: date, day: int) -> date:
    """Next calendar date landing on `day`-of-month, today included.

    due_day is capped at 28 in the schema, so every month has the day — no
    month-length clamping needed.
    """
    if today.day <= day:
        return today.replace(day=day)
    # roll to next month
    year = today.year + (1 if today.month == 12 else 0)
    month = 1 if today.month == 12 else today.month + 1
    return date(year, month, day)


def enrich(cards: list[dict], today: date | None = None) -> list[dict]:
    """Fill each card's `due` string from the stored due day (matched by name).

    Mutates and returns the list. Cards with no stored due day are left untouched
    (their `due` stays whatever the caller set — "" for live YNAB cards). The
    caller's `status` is preserved; this only sets the human-facing due string.
    """
    rows = _rows()
    if not rows:
        return cards
    today = today or date.today()
    for c in cards:
        row = rows.get(str(c.get("name", "")).lower())
        if row is None:
            continue
        if row["last4"]:
            c["last4"] = row["last4"]
        day = row["due_day"]
        nxt = _next_occurrence(today, day)
        c["due"] = f"due {nxt.strftime('%b').lower()} {day}"
        c["due_date"] = nxt.isoformat()
        c["due_in_days"] = (nxt - today).days
    return cards
