"""Home-page data assembly for the Hub.

Everything /api/home and the home shell need, and nothing that serves a route:
the schedule builder, the next-trip lookup, the subscription merge, the card
snapshot, and the two top-level shapes (_build_home_data, _shell_data). Split out
of app.py 2026-07-29, which was 1104 lines and half of them this.

Imported by app.py after its sys.path bootstrap, which is what makes the
dashboard-level modules below (gcal, cards, ynab, ...) importable at all.
"""
from __future__ import annotations

import calendar
import json
import re
import socket
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

import briefing_snapshot
import cards
import gcal
import gmail
import schedule_logic
import tasks
from finances import book
from hub_modules import MODULES as _MODULES
from vault_path import vault_root

VAULT = vault_root()
TRIPS_DB = VAULT / "data" / "trips.db"

# --- last-good cache for the network-bound panels -------------------------------
#
# gcal and ynab both swallow their own failures and hand back an empty list, so
# with no internet the schedule, the subscriptions and the card balances all render
# blank. That reads exactly like a genuinely quiet day, which is the problem.
#
# The fix is deliberately narrow: a saved copy is used ONLY when the machine has no
# network at all. When it IS online, an empty result is passed through untouched,
# so an expired Google login or a dead YNAB token still shows blank and still gets
# noticed. Masking a real breakage behind plausible old numbers is a worse failure
# than a blank panel, and it is the one this narrowness buys off.
_LAST_GOOD = Path(__file__).parent.parent / "home-last-good.json"
_LAST_GOOD_LOCK = threading.Lock()   # the three panels refresh on worker threads
_PROBE: tuple[float, bool] | None = None


def _online() -> bool:
    """One TCP probe, memoised for 30s.

    8.8.8.8:53 rather than a hostname, so this answers "is there a network" without
    depending on DNS. A box that routes but cannot resolve reads as online here and
    so gets blank panels — correct, because that IS something broken rather than
    something absent.

    ponytail: a socket, not a connectivity library. 1.5s is the ceiling it can add
    to a page load, and only when the network is black-holing rather than refusing.
    """
    global _PROBE
    if _PROBE and time.monotonic() - _PROBE[0] < 30:
        return _PROBE[1]
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=1.5).close()
        ok = True
    except OSError:
        ok = False
    _PROBE = (time.monotonic(), ok)
    return ok


def _cache_read() -> dict:
    try:
        return json.loads(_LAST_GOOD.read_text())
    except (OSError, ValueError):
        return {}


def _last_good(key: str, fetch):
    """Live data when there is a network; the last live data when there is not.

    Only a non-empty result is saved, so one failed refresh can never overwrite a
    good copy with nothing.
    """
    if not _online():
        entry = _cache_read().get(key)
        return entry["data"] if entry else fetch()
    data = fetch()
    if data:
        with _LAST_GOOD_LOCK:
            store = _cache_read()
            store[key] = {"at": int(time.time() * 1000), "data": data}
            try:
                _LAST_GOOD.write_text(json.dumps(store))
            except OSError:
                pass  # a cache we cannot write is not a reason to fail the page
    return data


def _cached_at() -> int | None:
    """When the saved copy being served was taken, or None if this is live data.

    Drives the offline banner in App.jsx. Newest entry wins: it is the freshest
    thing on screen, so it is the most generous honest thing to claim.
    """
    if _online():
        return None
    ats = [e["at"] for e in _cache_read().values() if isinstance(e, dict) and "at" in e]
    return max(ats) if ats else None


_MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _db(path: Path):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def _next_trip() -> dict:
    today = date.today().isoformat()
    con = _db(TRIPS_DB)
    cur = con.cursor()
    # start_date != '' guards a half-populated row: end_date >= today already
    # excludes blank end_dates, but a row with a valid future end_date and a
    # blank start_date would otherwise reach date.fromisoformat('') below.
    cur.execute(
        "SELECT id, name, destination, start_date, end_date FROM trips "
        "WHERE start_date != '' AND end_date >= ? ORDER BY start_date LIMIT 1",
        (today,),
    )
    row = cur.fetchone()
    # what is settled for it: the booked outbound flight and stay, and who is coming
    fl = st = None
    who = []
    if row:
        fl = cur.execute(
            "SELECT airline, flight_num, from_airport, to_airport, departure_time FROM flights "
            "WHERE trip_id = ? AND direction = 'outbound' AND status = 'booked' ORDER BY id LIMIT 1",
            (row["id"],)).fetchone()
        st = cur.execute(
            "SELECT name FROM housing WHERE trip_id = ? AND status = 'booked' ORDER BY id LIMIT 1",
            (row["id"],)).fetchone()
        who = [r["name"].split()[0] for r in cur.execute(
            "SELECT name FROM members WHERE trip_id = ? AND name != 'Sam Rivera' ORDER BY id", (row["id"],))]
    con.close()

    if not row:
        return {"days": 0, "dest": "no trips planned", "window": ""}

    try:
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
    except ValueError:
        # A trip row carries a malformed (non-empty but invalid) date. Treat as
        # "nothing planned" rather than 500 the /api/home hydrate.
        return {"days": 0, "dest": "no trips planned", "window": ""}
    days_away = (start - date.today()).days

    sm, em = _MONTHS[start.month - 1], _MONTHS[end.month - 1]
    window = (
        f"{sm} {start.day} – {em} {end.day}"
        if sm != em
        else f"{sm} {start.day} – {end.day}"
    )

    dest = row["destination"] or row["name"]
    dest = dest.split(",")[0].strip()
    # "Dec 16, 5:50 AM" -> "5:50a"; the date is the trip's first day already shown
    dep = (fl["departure_time"] or "").split(",")[-1].strip().lower().replace(" am", "a").replace(" pm", "p") if fl else ""
    return {"days": max(0, days_away), "dest": dest, "window": window, "nights": (end - start).days,
            "url": f"/trips/{row['id']}",
            "flight": f"{fl['flight_num'] or fl['airline']} {fl['from_airport']} → {fl['to_airport']}" + (f" · {dep}" if dep else "") if fl else "",
            "stay": st["name"] if st else "", "with": who}


_DIGEST_CITATION_RE = re.compile(r"\[#\d+\]")


def _first_digest_line(markdown: str) -> str | None:
    """First non-heading, non-empty line of a digest, citations stripped."""
    for line in markdown.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return _DIGEST_CITATION_RE.sub("", line).strip()
    return None


def _news_card() -> dict:
    """Home card snapshot: today's reporting-lane cluster count + the digest's
    first line. Must never raise -- news.db/news-cache.db may not exist yet,
    may not be migrated, or may not be seeded, and a missing card is better
    than a broken home page (see _last_good's masking rule above for why that
    tradeoff is the right one everywhere else in this file too).

    last_seen is stored UTC (news/cluster.py); "today" is compared as the real
    UTC range spanning local midnight-to-midnight, not a LIKE against the UTC
    date string -- a LIKE match on date.today() undercounts every evening,
    since local evening is already tomorrow's UTC date for hours at a time.
    """
    try:
        from news import db as news_db

        today = date.today()
        # date.today() is local; combine() on a naive datetime + astimezone()
        # interprets it as the system's local time, same "local" date.today()
        # already assumed -- no new timezone dependency, just the correct
        # comparison against a UTC column.
        local_midnight = datetime.combine(today, dt_time.min)
        start_utc = local_midnight.astimezone(timezone.utc).isoformat()
        end_utc = (local_midnight + timedelta(days=1)).astimezone(timezone.utc).isoformat()

        reporting_ids = [s["id"] for s in news_db.list_sources() if s.get("lane") == "reporting"]
        clusters_today = 0
        if reporting_ids:
            placeholders = ", ".join("?" * len(reporting_ids))
            with news_db._cache() as conn:
                # Driven from today's clusters, not from every reporting item: the
                # item-first form took 11s on the 54k-item cache (migration 003).
                clusters_today = conn.execute(
                    f"SELECT COUNT(*) FROM clusters c "  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
                    f"WHERE c.last_seen >= ? AND c.last_seen < ? AND EXISTS ("
                    f"SELECT 1 FROM items i WHERE i.cluster_id = c.id "
                    f"AND i.source_id IN ({placeholders}))",
                    (start_utc, end_utc, *reporting_ids),
                ).fetchone()[0]

        digest = news_db.get_digest(today.isoformat())
        digest_line = _first_digest_line(digest["markdown"]) if digest else None

        return {"clusters_today": clusters_today, "digest_line": digest_line}
    except Exception:
        return {"clusters_today": 0, "digest_line": None}


def _event_minutes(time_str: str) -> int:
    """Parse a schedule time string ("9:00a", "12:30p") to minutes past midnight
    for chronological sorting. All-day / unparseable strings sort to 0, but the
    day-sort keys all-day events ahead of timed ones separately.

    Both meridiem spellings parse. gcal now emits "9:00a", but a payload cached
    in the old "9:00am" shape has to keep sorting into the right slot rather than
    silently collapsing to 0 and jumping to the top of the day."""
    m = re.match(r"(\d{1,2}):(\d{2})\s*([ap])?m?", time_str.strip().lower())
    if not m:
        return 0
    h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return h * 60 + mn


def _trips_in_window(window_start: date, end_window: str) -> list[dict]:
    con = _db(TRIPS_DB)
    cur = con.cursor()
    cur.execute(
        "SELECT name, start_date, end_date FROM trips "
        "WHERE start_date <= ? AND end_date >= ? ORDER BY start_date",
        (end_window, window_start.isoformat()),
    )
    # Parse each trip's dates once here (not per-day below) and skip any row whose
    # dates are blank or malformed — date.fromisoformat('') would otherwise raise
    # and 500 the /api/home hydrate.
    trips_in_window = []
    for r in cur.fetchall():
        try:
            trips_in_window.append(
                {
                    "name": r["name"],
                    "start": date.fromisoformat(r["start_date"]),
                    "end": date.fromisoformat(r["end_date"]),
                }
            )
        except ValueError:
            continue
    con.close()
    return trips_in_window


def _gcal_events_by_date(today: date) -> dict[str, list]:
    """Merge gcal events by *logical* day (when authenticated). days_back=7 so the
    full past week is in the window alongside today + the next 7 days. An after-
    midnight event that chains back to the prior evening (e.g. 1-3am at a bar)
    buckets onto the night it belongs to, not its clock date — see
    schedule_logic.assign_logical_days. earliest_day clamps the rollback so an
    early event on the first rendered day can't fall out the bottom of the window.
    """
    gcal_by_date: dict[str, list] = {}
    if gcal.is_authenticated():
        earliest_day = (today - timedelta(days=7)).isoformat()
        for ev, logical_day in schedule_logic.assign_logical_days(
            _last_good("gcal", lambda: gcal.fetch_week_events(days=15, days_back=7)),
            earliest_day=earliest_day,
        ):
            gcal_by_date.setdefault(logical_day, []).append(ev)
    return gcal_by_date


def _booked_stays() -> list[dict]:
    con = _db(TRIPS_DB)
    try:
        return [dict(r) for r in con.execute(
            "SELECT address, check_in_method, checkout_tasks FROM housing WHERE status = 'booked'")]
    except sqlite3.OperationalError:   # a trips.db without the stay columns: no stay asks, never a 500
        return []
    finally:
        con.close()


_HOUSE_NO = re.compile(r"(?:^|,)\s*(\d+)\s")
_ZIP = re.compile(r"\b(\d{5})\b")


def _stay_prep(summary: str, location: str, stays: list[dict]) -> list[str] | None:
    """What a booked stay itself asks at check-in or checkout (door code, "start the
    dishwasher"), for the Today card's prep list. The calendar event and the stay row
    spell the street differently ("W 70th Dr" / "West 70th Drive"), so they are
    matched on house number plus ZIP. No guessing: no match or no text gives None."""
    col = ("check_in_method" if re.search(r"check.?in", summary or "", re.I)
           else "checkout_tasks" if re.search(r"check.?out", summary or "", re.I) else None)
    if not col or not location:
        return None
    no, zips = _HOUSE_NO.search(location), _ZIP.findall(location)
    if not no or not zips:
        return None
    for st in stays:
        a = st.get("address") or ""
        sno = _HOUSE_NO.search(a)
        if sno and sno.group(1) == no.group(1) and zips[-1] in _ZIP.findall(a):
            lines = [ln.strip() for ln in (st.get(col) or "").splitlines() if ln.strip()]
            return lines or None
    return None


def _day_events(d: date, d_str: str, trips_in_window: list[dict], gcal_by_date: dict[str, list],
                stays: list[dict] | None = None) -> list[dict]:
    events = []

    for t in trips_in_window:
        if t["start"] <= d <= t["end"]:
            events.append(
                {
                    "time": "all day",
                    # proper case kept; dashboard lowercases via CSS for display
                    "name": t["name"] or "trip",
                    "sub": "trip",
                }
            )

    for ev in gcal_by_date.get(d_str, []):
        # Link every Tomato event (all-day deadlines + timed deadlines/
        # interviews/appointments) to a canonical task row so the pip can
        # complete/reopen by task_key. sync_event returns None only for
        # non-task events. Timed tasks render the checkable pip in their slot.
        link = tasks.sync_event(ev)
        # A "rolled" event crossed midnight into this day's clock but belongs
        # to the previous night (logical day), so its calendar date differs
        # from the bucket it landed in. It must sort to the END of the day.
        rolled = bool(ev.get("start_dt")) and ev.get("date") != d_str
        events.append(
            {
                "time": ev["time"],
                "timeEnd": ev.get("time_end", ""),
                "name": ev["summary"],
                "sub": "cal",
                "task": ev.get("color_id") == "11",
                "taskId": link["task_key"] if link else None,
                "done": link["done"] if link else False,
                "id": ev.get("id", ""),
                "calendarId": ev.get("calendar_id", ""),
                "color": ev.get("color", ""),
                "description": ev.get("description", ""),
                "location": ev.get("location", ""),
                "link": ev.get("link", ""),
                "startDt": ev.get("start_dt", ""),
                "endDt": ev.get("end_dt", ""),
                "allDay": ev.get("all_day", False),
                "rolled": rolled,
                "stayPrep": _stay_prep(ev["summary"], ev.get("location", ""), stays or []),
            }
        )

    # All-day events (trips + all-day cal events, tasks included) come first;
    # everything else sorts chronologically by start time. A rolled past-
    # midnight event gets +24h so it lands after the evening it continues,
    # not at the top of the day. Tasks get no special placement.
    events.sort(
        key=lambda e: (
            0 if (e.get("allDay") or e.get("time") == "all day") else 1,
            _event_minutes(e.get("time", "")) + (1440 if e.get("rolled") else 0),
        )
    )
    return events


def _day_label(i: int, d: date) -> str:
    if i == -1:
        return "yesterday"
    if i == 0:
        return "today"
    if i == 1:
        return "tomorrow"
    return d.strftime("%A").lower()


def _build_schedule() -> list:
    today = date.today()
    # The briefing navigates a full -7..+7 window (the Schedule band slices this
    # back to its own yesterday->+6 view client-side).
    window_start = today - timedelta(days=7)
    end_window = (today + timedelta(days=7)).isoformat()

    trips_in_window = _trips_in_window(window_start, end_window)
    gcal_by_date = _gcal_events_by_date(today)
    stays = _booked_stays()

    # i = -7..-1 is the past week; 0 is today; 1..7 are the next seven days.
    days_data = []
    for i in range(-7, 8):
        d = today + timedelta(days=i)
        d_str = d.isoformat()
        days_data.append(
            {
                "label": _day_label(i, d),
                "date": f"{_MONTHS[d.month - 1]} {d.day}",
                "isoDate": d_str,
                "isToday": i == 0,
                "events": _day_events(d, d_str, trips_in_window, gcal_by_date, stays),
            }
        )

    return days_data


# hardcoded fallback — used when YNAB is not configured. Due strings are
# overwritten by cards.enrich() from data/cards.db; kept here as a sensible
# offline default (day-of-month matches the seeded cards).
_CARDS_FALLBACK = [
    {
        "name": "Chase Freedom Unlimited",
        "last4": "",
        "due": "due jun 14",
        "amt": "$110.00",
        "status": "due",
    },
    {
        "name": "Chase Sapphire Preferred",
        "last4": "",
        "due": "due jun 13",
        "amt": "$32.00",
        "status": "due",
    },
    {
        "name": "Discover It Chrome",
        "last4": "",
        "due": "due jun 22",
        "amt": "$45.00",
        "status": "due",
    },
]

# Subscriptions not (yet) auto-detected from YNAB — billed off-budget (Stripe,
# Google Play) or too new to have 2 charges in the 90-day window. `due_day` is the
# billing day-of-month; _build_subs renders a live "next billing" date from it so
# these roll forward instead of going stale. `amt` is the actual charge incl. tax.
# Found by scanning Gmail receipts 2026-06-25 (Anthropic / Wispr / Google Play).
# Google AI Pro is intro-priced $4.99 until 2026-09-16, then ~$19.99 — update then.
#
# Dedup: once a manual sub gets 2 charges in YNAB's 90-day window it auto-detects
# and would double-list. _build_subs suppresses the YNAB row automatically by
# matching the leading word of its payee to the leading word of the display name
# ("Google AI Pro (5 TB)" ⟷ payee "Google"/"Google One") — no payee strings to
# hand-maintain. `ynab_payees` is only needed
# for the rare case where YNAB's payee shares NO word with the display name: Claude
# Max bills as "Anthropic", so it gets one explicit alias. Add an alias here only
# when a sub's YNAB payee turns out to be a different word than its name.
_SUBS_MANUAL = [
    {"name": "Claude Max", "cycle": "monthly", "amt": "$100.00", "due_day": 12,
     "ynab_payees": ["Anthropic"]},
]

# Payee names from YNAB to drop (canceled or not a subscription).
_SUBS_EXCLUDE = {"Steam", "WISPR", "Crunchyroll", "McDonald's", "McDonalds"}
# Leading words of payees to drop wholesale: Google AI Pro was cancelled (2026-10-17).
_SUBS_EXCLUDE_TOKENS = {"google", "mcdonald", "mcdonalds"}

# Map YNAB payee names → display names.
_SUBS_RENAME = {
    "Supercell": "Clash of Clans Gold Pass",
    "Apple Digital Services": "iCloud+ 2TB",
    "Spotify": "Spotify Family Plan",
}

# The launcher module list is the single source of truth in hub_modules.py — see
# that file for why it can't live here (app.py is __main__). work/api.py imports
# the same list, and /hub-modules.js serves it to every page's window.MODULES.


_MON_ABBR = ["jan", "feb", "mar", "apr", "may", "jun",
             "jul", "aug", "sep", "oct", "nov", "dec"]

# Leading articles skipped so the "distinctive" leading word is used, not "the".
_NAME_STOP = {"the", "a", "an"}


def _first_token(s: str) -> str:
    """Leading distinctive word of a name/payee, lowercased — the automatic match
    key between a YNAB-detected payee and a manually-tracked sub, so payee strings
    don't have to be hand-maintained. 'Google AI Pro (5 TB)' -> 'google';
    'Wispr Flow' -> 'wispr'; 'The Economist' -> 'economist'."""
    for t in re.findall(r"[a-z0-9]+", (s or "").lower()):
        if t not in _NAME_STOP:
            return t
    return ""


def _next_billing_str(due_day: int) -> str:
    """Next calendar date landing on `due_day`-of-month (today inclusive), as
    'mon d' — matches the YNAB-detected subs' next_billing format. due_day is a
    stable 1-28 so every month has the day."""
    today = date.today()
    if today.day <= due_day:
        nxt = today.replace(day=due_day)
    else:
        y = today.year + (1 if today.month == 12 else 0)
        m = 1 if today.month == 12 else today.month + 1
        nxt = date(y, m, due_day)
    return f"{_MON_ABBR[nxt.month - 1]} {nxt.day}"


def _days_until(mon_d, today=None):
    """Days from today to a 'mon d' next-billing string, or None when it is not
    one ("new, from email"). The year is whichever puts the date nearest today."""
    today = today or date.today()
    try:
        mon, d = (mon_d or "").split()
        m, d = _MON_ABBR.index(mon) + 1, int(d)
        return min(((date(y, m, d) - today).days for y in (today.year - 1, today.year, today.year + 1)), key=abs)
    except ValueError:
        return None


def _manual_subs() -> tuple[list[dict], set[str], set[str]]:
    """Manual subs carry a billing day-of-month; render it to a live next-billing
    date so the dates roll forward each month instead of going stale. Also builds
    two suppression sets so a later YNAB auto-detection of the same sub is dropped
    and the manual entry stays canonical: `suppress_tokens` is the leading word of
    each display name (the automatic, no-maintenance match); `suppress_payees`
    holds explicit `ynab_payees` aliases for the rare payee that shares no word
    with the name (e.g. Anthropic ⟷ Claude Max). Both keys popped before return.
    """
    manual = []
    suppress_payees = set()
    suppress_tokens = set()
    for s in _SUBS_MANUAL:
        s = dict(s)
        due_day = s.pop("due_day", None)
        if due_day is not None:
            s["next_billing"] = _next_billing_str(due_day)
        for p in s.pop("ynab_payees", []):
            suppress_payees.add(p.lower())
        suppress_tokens.add(_first_token(s["name"]))
        manual.append(s)
    suppress_tokens.discard("")
    return manual, suppress_tokens, suppress_payees


def _ynab_subs_filtered(suppress_tokens: set[str], suppress_payees: set[str], manual_names: set[str]) -> list[dict]:
    if not book.is_configured():
        return []
    ynab_subs = []
    for s in _last_good("ynab_subs", book.fetch_subscriptions):
        name = s["name"]
        if name in _SUBS_EXCLUDE or name.lower() in manual_names:
            continue
        if _first_token(name) in _SUBS_EXCLUDE_TOKENS:
            continue
        # Drop YNAB's row for a sub we already track manually — matched on the
        # leading word of the payee (automatic) or an explicit rename alias.
        if (_first_token(name) in suppress_tokens or name.lower() in suppress_payees
                or _first_token(name) in {_first_token(p) for p in suppress_payees}):
            continue
        if name in _SUBS_RENAME:
            s = {**s, "name": _SUBS_RENAME[name]}
        ynab_subs.append(s)
    return ynab_subs


_SUBS_LABEL = "VI. Finances/B. Invoices/3. Digital/a. Subscriptions"
_SUB_ENDED = re.compile(r"cancel|ended|expire|terminat|sorry to see you go", re.I)
# the product a mail is about, when the sender is a billing processor (link.com bills SimpleFIN Bridge)
_SUB_NAME = re.compile(r"welcome to (.+)|your (.+?) subscription", re.I)
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov"}  # the "co" in foo.co.uk
_CHARGE_WINDOW = 3  # days between a subscription email and the charge it goes with


def _domain_brand(domain: str) -> str:
    """'email.openai.com' -> 'openai', 'notion.so' -> 'notion', 'foo.co.uk' -> 'foo'."""
    parts = [p for p in (domain or "").lower().split(".") if p][:-1]  # drop the TLD
    if len(parts) > 1 and parts[-1] in _SECOND_LEVEL:
        parts = parts[:-1]
    return parts[-1] if parts else ""


def _month_on(d: date, day: int, k: int) -> date:
    """`k` calendar months after `d`, on `day` (clamped to the month's last day)."""
    y, m = divmod(d.month - 1 + k, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def _next_due(last: date, day: int, today: date) -> date:
    """The first monthly billing date on `day` after the period `last` paid for that
    is not before today. A charge posted across a month end (day 31 posting on the
    2nd) belongs to the month whose `day` it is nearest."""
    base = min((_month_on(last, day, k) for k in (-1, 0, 1)), key=lambda p: abs((p - last).days))
    k = 1
    while _month_on(base, day, k) < today:
        k += 1
    return _month_on(base, day, k)


def _sub_charges(charges: list[dict], mailed: list[date]) -> tuple[list[dict], int]:
    """The brand's subscription charges, oldest first, and its billing day. The charge
    nearest each email (within a few days) is an anchor, so a receipt re-anchors and an
    intro price that ends is picked up; a charge on the anchor's day of the month within
    25% of the previous one is a renewal; a one-off order from the store is neither."""
    ts = sorted(charges, key=lambda t: t["date"])
    when = [date.fromisoformat(t["date"]) for t in ts]
    anchors = set()
    for d in mailed:
        near = [i for i, w in enumerate(when) if abs((w - d).days) <= _CHARGE_WINDOW]
        if near:
            anchors.add(min(near, key=lambda i: abs((when[i] - d).days)))
    out, day = [], 0
    for i, t in enumerate(ts):
        dom = abs(when[i].day - day)
        if i in anchors:
            out.append(t); day = when[i].day
        elif (out and min(dom, 31 - dom) <= _CHARGE_WINDOW
              and abs(t["amount"] - out[-1]["amount"]) <= abs(out[-1]["amount"]) / 4):
            out.append(t)
    return out, day


def _email_subs(skip_tokens: set[str], today: date | None = None) -> list[dict]:
    """Subscriptions the Gmail lane filed under Digital/Subscriptions (welcome,
    receipt, renewal mail), one per sender brand. Email adds the subscription; the
    book prices it from that payee's newest subscription charge (`_sub_charges`).
    Without one it shows as "new" and no amount until its newest email is 90 days
    old; one whose last charge is over 45 days old has stopped and is dropped. A brand whose newest email reads as cancelled is dropped. Brands the
    manual list already tracks (`skip_tokens`) are skipped."""
    today = today or date.today()
    try:
        from contextlib import closing
        from automations import db as adb
        with closing(adb.connect()) as c:
            rows = c.execute(
                "SELECT sender, domain, subject, received_at FROM gmail_item "
                "WHERE label = ? AND state != 'stale' ORDER BY received_at", (_SUBS_LABEL,)).fetchall()
    except Exception:
        return []
    latest, mailed = {}, {}
    for r in rows:
        brand = _domain_brand(r["domain"])
        if brand in {"google", "gmail", "googleplay"} or not brand:
            continue
        latest[brand] = r  # rows are oldest first, so the last one wins
        try:
            mailed.setdefault(brand, []).append(date.fromisoformat((r["received_at"] or "")[:10]))
        except ValueError:
            pass
    live = {b: r for b, r in latest.items()
            if b not in skip_tokens and not _SUB_ENDED.search(r["subject"] or "")}
    charges = {}
    try:
        # back to the oldest live email so a renewal still finds its anchor charge;
        # ponytail: capped at a year, a sub whose only email is older drops off Home
        # (the bank's recurring-payee list still lists it)
        oldest = min((d for b in live for d in mailed.get(b, [])), default=today)
        since = max(min(oldest - timedelta(days=_CHARGE_WINDOW), today - timedelta(days=90)),
                    today - timedelta(days=365))
        for t in book._load(since.isoformat()):
            if t["amount"] < 0 and t.get("payee_name"):
                charges.setdefault(_first_token(t["payee_name"]), []).append(t)
    except Exception:
        pass
    out = []
    for brand, r in live.items():
        m = _SUB_NAME.search(r["subject"] or "")
        sub = {"name": ((m.group(1) or m.group(2)).strip() if m else brand.title()), "cycle": "monthly", "_brand": brand}
        # ponytail: a one-off order that is the nearest charge to an email, or that
        # matches payee word, day of month and price band, still reads as the price
        hits, day = _sub_charges(charges.get(brand) or charges.get(_first_token(sub["name"]), []), mailed.get(brand, []))
        if hits and (today - date.fromisoformat(hits[-1]["date"])).days > 45:
            continue  # billed, then stopped: cancelled without a cancel email
        if not hits and (not mailed.get(brand) or (today - max(mailed[brand])).days > 90):
            continue
        if hits:
            last = hits[-1]
            nxt = _next_due(date.fromisoformat(last["date"]), day, today)
            sub["amt"] = f"${abs(last['amount']) / 1000.0:.2f}"
            sub["next_billing"] = f"{_MON_ABBR[nxt.month - 1]} {nxt.day}"
        else:
            sub["amt"] = "—"
            sub["next_billing"] = "new, from email"
        out.append(sub)
    return out


def _build_subs() -> list:
    """Merge YNAB-detected subscriptions with the manual supplement list.

    Manual entries win on name collision. YNAB entries are renamed and filtered
    before merging. Result sorted by amount descending.
    """
    manual, suppress_tokens, suppress_payees = _manual_subs()
    manual_names = {s["name"].lower() for s in manual}
    ynab_subs = _ynab_subs_filtered(suppress_tokens, suppress_payees, manual_names)
    email = _email_subs(suppress_tokens | {_first_token(p) for p in suppress_payees})
    # the email row wins over a YNAB row for the same brand
    email_tokens = {_first_token(s["name"]) for s in email} | {s["_brand"] for s in email}
    ynab_subs = [s for s in ynab_subs if _first_token(s["name"]) not in email_tokens]
    combined = manual + [{k: v for k, v in s.items() if k != "_brand"} for s in email] + ynab_subs
    today = date.today()
    for s in combined:
        s["days"] = _days_until(s.get("next_billing"), today)
        # a renewal estimate the bank has not posted yet is never "late": roll it
        # forward a calendar month at a time (every sub here is monthly)
        if s["days"] is not None and s["days"] < 0:
            due = today + timedelta(days=s["days"])
            nxt = due if due >= today else _next_due(due, due.day, today)
            s["next_billing"] = f"{_MON_ABBR[nxt.month - 1]} {nxt.day}"
            s["days"] = (nxt - today).days

    def _amt_val(s):
        try:
            return float(s["amt"].lstrip("$"))
        except (ValueError, AttributeError):
            return 0.0

    combined.sort(key=_amt_val, reverse=True)
    return combined


def _cards_synced_at() -> int | None:
    """Only the 'synced' label depends on this, so a book error loses the label, not Home."""
    try:
        return book.last_sync_at() if book.is_configured() else None
    except Exception:
        return None


def _cards_live() -> list:
    raw = (_last_good("ynab_cards", book.fetch_credit_cards)
           if book.is_configured() else _CARDS_FALLBACK)
    # YNAB has no due dates — merge in the stored payment-due days from cards.db.
    return cards.enrich(raw)


def _build_home_data() -> dict:
    # These three are network-bound (gcal, ynab x2) and independent, so they run
    # concurrently instead of serially. The inbox panel was retired 2026-06-30 (the
    # permanent today-zone restructure), dropping the two Gmail fetches that fed it.
    # The clients are thread-safe for these read calls (verified 2026-06-16).
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_cards = ex.submit(_cards_live)
        f_schedule = ex.submit(_build_schedule)
        f_subs = ex.submit(_build_subs)
        cards_list = f_cards.result()
        schedule = f_schedule.result()
        subs = f_subs.result()

    return {
        # epoch ms when this data was fetched — ynab is pulled live in this call,
        # so the frontend renders an honest "synced Xm ago" off it.
        "GENERATED_AT": int(datetime.now().timestamp() * 1000),
        # Non-null only when this box has no network and the calendar/money panels
        # are being served from the saved copy. App.jsx turns it into the banner.
        "CACHED_AT": _cached_at(),
        "SCHEDULE": schedule,
        "CARDS": cards_list,
        # when the card balances last came from the bank (SimpleFIN into book.db)
        "CARDS_SYNCED_AT": _cards_synced_at(),
        "SUBS": subs,
        "TASKS": tasks.list_active(),
        "TASKS_COMPLETED": tasks.list_completed(),
        # frozen per-day briefing bits (forecast + bring/prep) for past days, so a
        # rolled-over day still shows what was true then. See briefing_snapshot.
        "BRIEFING_SNAPSHOTS": briefing_snapshot.get_all(),
        "TRIP": _next_trip(),
        "NEWS": _news_card(),
        "MODULES": _MODULES,
        "CONNECTORS": {
            "gcal": gcal.is_authenticated(),
            "gmail": gmail.is_authenticated(),
            "ynab": book.is_configured(),
        },
    }


def _shell_data() -> dict:
    """Instant, no-network payload for the initial home document. Carries only the
    static bits the shell needs to render immediately (MODULES); the network-bound
    panels (schedule, cards, subs, tasks, trip, connectors) are left null and
    loaded by the React app via /api/home after first paint. This is what makes the
    page interactive in ~0ms instead of blocking ~0.9s on Google/YNAB before any
    HTML is sent. `null` signals "not loaded yet" to App.jsx (see its progressive
    fetch). Completing/reopening a task and the initial hydrate all go through the
    full /api/home below."""
    return {
        "GENERATED_AT": None,
        "SCHEDULE": None,
        "CARDS": None,
        "SUBS": None,
        "TASKS": None,
        "TASKS_COMPLETED": None,
        "BRIEFING_SNAPSHOTS": None,
        "TRIP": None,
        "NEWS": None,
        "MODULES": _MODULES,
        "CONNECTORS": None,
    }
