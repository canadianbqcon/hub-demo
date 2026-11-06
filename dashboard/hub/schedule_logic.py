"""Pure logic for assigning a calendar event to its *logical day* — the day it
belongs to for the schedule panel, which is not always the day its clock says.

The model (Sam's): a day owns the time from its own midnight through NOON of
the next calendar day. There is no backward reach before its own midnight. So an
after-midnight event is, by default, the tail of the *previous* night — but only
when it actually chains back to that evening. A genuinely new day's early event
(a 4am flight that follows sleep) stays on its own day.

Decision for a timed event whose start is between 00:00 and 12:00 of calendar
day X (events at/after noon are never candidates — they keep day X):

  1. CHAINED — walk backward through the merged timeline of timed events; if you
     can reach before midnight(X) without ever crossing a >= SLEEP_GAP idle gap,
     the event is continuous with the prior evening -> day X-1. (The bar run.)
  2. ISOLATED + new-day keyword (flight/airport/depart/shift) -> day X. Catches a
     4am departure flight that sits alone after sleep.
  3. ISOLATED, no keyword -> before LATE_NIGHT_CUTOFF (5am) leans to the prior
     night (X-1); at/after it reads as morning (X). Keeps a lone 9am brunch on
     its own day, a lone 2am drink on the night before.

Chaining is checked FIRST so a late-night arrival flight that is continuous with
the evening (flight lands 1am, Uber home 1:30am) is not severed by its keyword.

No I/O, no Google client. Unit-tested standalone:
    python3 dashboard/hub/tests/test_schedule_logic.py
"""

from __future__ import annotations

from datetime import datetime, timedelta

# An idle gap this long or longer is treated as the day break (sleep).
SLEEP_GAP = timedelta(hours=3)
# An isolated early event before this hour leans to the prior night.
LATE_NIGHT_CUTOFF = 5
# Only events starting before this hour (noon) are rollback candidates — the
# forward "12 hours into the next day" rail.
ROLL_WINDOW_END = 12
# Title keywords that mark an isolated early event as a new-day anchor.
NEW_DAY_KEYWORDS = ("flight", "airport", "depart", "shift")


def _parse(dt_str: str):
    """Parse an event datetime string to an aware/naive datetime, mirroring the
    existing display parse (fetch_week_events) so we inherit its proven local-hour
    behavior. Returns None when there is no clock time (all-day) or on malformed
    input."""
    if not dt_str or "T" not in dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _title_is_new_day(summary: str) -> bool:
    s = (summary or "").lower()
    return any(k in s for k in NEW_DAY_KEYWORDS)


def _backward_block_start(
    i: int, start: datetime, starts: list[datetime], ends: list[datetime]
) -> datetime:
    """Earliest start reachable walking backward from timed[i] without crossing SLEEP_GAP."""
    cur_block_start = start
    j = i - 1
    while j >= 0:
        gap = cur_block_start - ends[j]
        if gap < timedelta(0):
            gap = timedelta(0)  # overlapping / concurrent -> connected
        if gap >= SLEEP_GAP:
            break
        if starts[j] < cur_block_start:
            cur_block_start = starts[j]
        j -= 1
    return cur_block_start


def _classify_logical_day(ev: dict, start: datetime, cal_day, midnight: datetime, cur_block_start: datetime):
    """CHAINED / new-day-keyword / late-night-cutoff rules from the module docstring."""
    if cur_block_start < midnight:
        return (midnight - timedelta(days=1)).date()
    if _title_is_new_day(ev.get("summary", "")):
        return cal_day
    if start.hour < LATE_NIGHT_CUTOFF:
        return (midnight - timedelta(days=1)).date()
    return cal_day


def assign_logical_days(events: list[dict], earliest_day: str | None = None):
    """Given the flat event list from gcal.fetch_week_events, return a list of
    (event, logical_day_str) pairs.

    Each event dict is expected to carry: ``date`` (YYYY-MM-DD of start),
    ``all_day`` (bool), ``summary``, ``start_dt`` and ``end_dt`` (ISO datetimes).

    ``earliest_day`` is a lower clamp ('YYYY-MM-DD'): an event never rolls before
    it, so a 2am event on the first rendered day cannot fall out the bottom of the
    window and vanish. Pass the earliest rendered day.
    """
    out: list[tuple[dict, str]] = []

    # All-day / untimed events keep their own date — there is no clock to reason
    # about, and they must NOT enter the timed timeline (a 0-length all-day "gap"
    # would otherwise bridge a real sleep gap).
    timed: list[tuple[datetime, datetime, dict]] = []
    for ev in events:
        start = _parse(ev.get("start_dt", ""))
        if ev.get("all_day") or start is None:
            out.append((ev, ev.get("date", "")))
            continue
        end = _parse(ev.get("end_dt", "")) or start
        if end < start:  # guard malformed end
            end = start
        timed.append((start, end, ev))

    timed.sort(key=lambda t: t[0])
    starts = [t[0] for t in timed]
    ends = [t[1] for t in timed]

    for i, (start, _, ev) in enumerate(timed):
        cal_day = start.date()
        # Not a candidate: at/after noon -> always its own day.
        if start.hour >= ROLL_WINDOW_END:
            out.append((ev, cal_day.isoformat()))
            continue

        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
        cur_block_start = _backward_block_start(i, start, starts, ends)
        logical = _classify_logical_day(ev, start, cal_day, midnight, cur_block_start)

        logical_str = logical.isoformat()
        # Bottom-edge clamp: never roll before the earliest rendered day.
        if earliest_day is not None and logical_str < earliest_day:
            logical_str = cal_day.isoformat()
        out.append((ev, logical_str))

    return out
