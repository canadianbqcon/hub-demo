from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import google_auth
from config import CONFIG_DIR
from google_auth import CREDENTIALS_FILE  # noqa: F401  (module surface)

logger = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).parent
TOKEN_FILE = CONFIG_DIR / "token.json"
CACHE_FILE = DASHBOARD_DIR / "calendar_cache.json"

SCOPES = ["https://www.googleapis.com/auth/calendar"]


_auth = google_auth.GoogleAuth(TOKEN_FILE, SCOPES)

has_credentials = _auth.has_credentials
is_authenticated = _auth.is_authenticated
needs_reauth = _auth.needs_reauth
get_auth_url = _auth.get_auth_url
handle_callback = _auth.handle_callback
_load_creds = _auth.load_creds


def _get_service():
    return _auth.service("calendar", "v3")


# Every read path here starts by listing the calendars, and that list is four rows
# that only change when Sam adds or removes a Google calendar. It was costing
# 500-600 ms per call — more than the batched event fetch it exists to set up, and
# over half of the home page's ~1 s hydrate. Ten minutes is orders of magnitude
# shorter than the thing ever changes and still collapses a session's worth of
# panels down to one call.
# ponytail: a module-level tuple, no eviction — there is exactly one entry.
_CAL_TTL = 600
_cal_cache: tuple[float, list] | None = None
_CAL_SKIP = ("holiday", "@import.calendar.google.com")


def _calendars(force: bool = False) -> list:
    """The calendars worth reading — holiday and import-only feeds dropped."""
    global _cal_cache
    if not force and _cal_cache and time.monotonic() - _cal_cache[0] < _CAL_TTL:
        return _cal_cache[1]
    # SpotOn's calendar is mirrored onto Personal as "Barback Shift" (hub/finances/shift_calendar.py
    # SPOTON_CAL); reading both showed every shift twice (mark 2026-11-11-003157 #2)
    items = [c for c in _get_service().calendarList().list().execute().get("items", [])
             if not any(k in c["id"] for k in _CAL_SKIP)
             and c.get("summary") != "Juniper & Co's Work Schedule"]
    _cal_cache = (time.monotonic(), items)
    return items


def _next_day(date: str) -> str:
    """An all-day event's end.date is EXCLUSIVE, so a trip through the 21st ends
    on the 22nd. The vault stores end_date inclusive (it is a day you are there),
    which is why every push has to add the day back."""
    from datetime import datetime, timedelta

    try:
        return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        return date


# ── "Is this already on the calendar?" ────────────────────────────────────────
# Both pushes below used to insert BLIND whenever their row carried no
# cal_event_id, and a row loses its id for ordinary reasons: it was typed into the
# board after the event was made by hand, it was imported, the id was cleared. So
# the board answered "I have no id" with "then it does not exist", which is a
# different claim, and made a second copy of an event already sitting there. The
# El Salvador trip carried both halves of the damage at once — the Atami day party
# on the calendar twice, and the wedding unlinked and one PATCH away from a third.
#
# Matching on the summary alone does not close it: the board's row is named
# "Wedding ceremony + reception" and the event is "Josh & Amanda's Wedding", which
# share no words. What they do share is the place. So a match is the same DAY plus
# either the same name or the same place, each normalised — accents folded, case
# dropped, punctuation collapsed — because the pair that motivated this differed
# by exactly an accent and a trailing country ("Fôret Bodas y Eventos, ... 1506"
# against "Foret Bodas y Eventos, ... 1506, El Salvador").
#
# ponytail: same-day-and-same-place is deliberately loose, and two genuinely
# different events at one venue on one day read as a match. That is the safe
# direction to be wrong in: the cost is a missing sync on a row nothing was
# syncing anyway, against a duplicate on his real calendar. Tighten it with an
# extended-property stamp on events the board itself writes if it ever bites.


def _norm(s: str) -> str:
    """Fold a name or an address to the part worth comparing."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _existing_event_id(service, date: str, summary: str, location: str) -> str:
    """The id of an event already on `date` that is plainly this same thing, else "".

    Returns the id WITHOUT touching the event. A hand-made event carries a real
    start time and a description the board cannot reproduce (the board writes a
    timed body only when the activity has a time and the trip's arrival airport
    has a zone, and never a description as full as a hand-made one), so
    adopting one and then pushing over it would flatten exactly what makes it
    worth keeping. The caller's job here is only to not insert a second copy.
    """
    if not date:
        return ""
    n_sum, n_loc = _norm(summary), _norm(location)
    if not n_sum and not n_loc:
        return ""
    try:
        items = (
            service.events()
            .list(calendarId="primary", timeMin=f"{date}T00:00:00Z",
                  timeMax=f"{_next_day(date)}T23:59:59Z", singleEvents=True,
                  maxResults=50)
            .execute()
            .get("items", [])
        )
    except Exception:
        logger.exception("_existing_event_id lookup failed for %s", date)
        return ""  # a failed lookup must not block the push
    for e in items:
        start = e["start"].get("date") or e["start"].get("dateTime", "")[:10]
        if start != date:
            continue
        e_sum, e_loc = _norm(e.get("summary", "")), _norm(e.get("location", ""))
        if n_sum and e_sum == n_sum:
            return e["id"]
        if n_loc and e_loc and (n_loc.startswith(e_loc) or e_loc.startswith(n_loc)):
            return e["id"]
    return ""


# ── Titles arrive pre-escaped from other people's calendars ───────────────────
# The Juniper & Co work-schedule calendar is written by the employer's rota tool,
# and it stores the title with the entity already in it: the event summary really
# is the eleven characters "Juniper &amp; Co Barback". Nothing here escaped it
# twice — we rendered faithfully what the feed said. So the fix belongs at the
# read boundary, once, rather than on the home page that happened to show it.
#
# Only the entities that CANNOT become markup are decoded. &lt; and &gt; are left
# alone on purpose: an event title is other people's text arriving over the wire,
# and turning "&lt;script&gt;" back into a tag would hand a calendar invite a way
# into any consumer that ever renders a title as HTML. An ampersand cannot open a
# tag, so decoding it costs nothing.
_ENTITIES = {"&amp;": "&", "&#38;": "&", "&quot;": '"', "&#34;": '"',
             "&#39;": "'", "&apos;": "'", "&nbsp;": " "}


# The same rota tool writes the venue as a bare name ("Juniper and Co"), which no
# geocoder places, so the Home "getting there" card had no pin, ride links or route
# for those shifts (2026-11-03 mark). Bare venue names are swapped for the address
# of record (wiki/notes/calendar-event-conventions) at this read boundary.
_VENUES = {"juniper and co": "Juniper & Co, 200 Example Ave, New York, NY 10002",
           "juniper & co": "Juniper & Co, 200 Example Ave, New York, NY 10002"}


def _relocate(loc: str) -> str:
    """A bare known-venue name becomes its full address; anything else is kept."""
    loc = _detitle(loc or "").strip()
    return _VENUES.get(loc.lower(), loc)


def _detitle(s: str) -> str:
    """Undo the safe HTML entities an upstream calendar baked into a title."""
    s = s or ""
    for ent, ch in _ENTITIES.items():
        s = s.replace(ent, ch)
    return s


def push_trip(trip: dict) -> str:
    """Create or update the trip's Google Calendar all-day event. Returns event_id."""
    service = _get_service()
    body = {
        "summary": trip["name"],
        "location": trip.get("destination", ""),
        "start": {"date": trip.get("start_date", "")},
        "end": {"date": _next_day(trip.get("end_date", ""))},
    }
    cal_event_id = trip.get("cal_event_id")
    if cal_event_id:
        result = (
            service.events()
            .update(calendarId="primary", eventId=cal_event_id, body=body)
            .execute()
        )
        return result["id"]
    hit = _existing_event_id(service, body["start"]["date"], body["summary"],
                             body.get("location", ""))
    if hit:
        logger.info("push_trip: %r already on the calendar as %s, not inserting",
                    body["summary"], hit)
        return hit
    result = service.events().insert(calendarId="primary", body=body).execute()
    return result["id"]


def _clock(s: str) -> str:
    """'17:00', '5 PM' or '11:00 AM' as 'HH:MM'; "" when it is not a time."""
    s = (s or "").strip().upper().replace(".", "")
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            return datetime.strptime(s, fmt).strftime("%H:%M")
        except ValueError:
            pass
    return ""


def _when(activity: dict, date: str, tz: str) -> tuple[dict, dict]:
    """Start and end bodies. Timed in the destination zone when the activity has a
    start time and the trip has a zone; all-day otherwise."""
    start = _clock(activity.get("scheduled_time", ""))
    if not (tz and start):
        return {"date": date}, {"date": _next_day(date)}
    t0 = datetime.strptime(f"{date} {start}", "%Y-%m-%d %H:%M")
    end = _clock(activity.get("scheduled_time_end", ""))
    t1 = datetime.strptime(f"{date} {end}", "%Y-%m-%d %H:%M") if end else t0
    if t1 <= t0:
        t1 = t0 + timedelta(hours=1)  # ponytail: no end time means a one-hour block
    fmt = "%Y-%m-%dT%H:%M:00"
    return ({"dateTime": t0.strftime(fmt), "timeZone": tz},
            {"dateTime": t1.strftime(fmt), "timeZone": tz})


def push_activity(activity: dict, trip: dict) -> str:
    """Push a scheduled activity to Google Calendar: timed in the trip's zone
    (`trip["tz"]`) when it has a start time, all-day otherwise. Returns event_id."""
    service = _get_service()
    date = activity.get("scheduled_date", "")
    if not date:
        raise ValueError("activity has no scheduled_date")
    start, end = _when(activity, date, trip.get("tz", ""))
    desc_parts = []
    if activity.get("scheduled_time") and "date" in start:
        desc_parts.append(f"Time: {activity['scheduled_time']}")
    if activity.get("description"):
        desc_parts.append(activity["description"])
    if activity.get("url"):
        desc_parts.append(activity["url"])
    if trip.get("name"):
        desc_parts.append(f"Trip: {trip['name']}")
    body = {
        "summary": activity["name"],
        "location": activity.get("location", ""),
        "description": "\n".join(desc_parts),
        "start": start,
        "end": end,
    }
    cal_event_id = activity.get("cal_event_id")
    if cal_event_id:
        result = (
            service.events()
            .update(calendarId="primary", eventId=cal_event_id, body=body)
            .execute()
        )
        return result["id"]
    hit = _existing_event_id(service, date, body["summary"], body.get("location", ""))
    if hit:
        # Deliberately NOT stored on the row: the caller only writes back an id that
        # differs from the one it passed in, and an unowned event should stay unowned.
        logger.info("push_activity: %r already on the calendar as %s, not inserting",
                    body["summary"], hit)
        return activity.get("cal_event_id") or ""
    result = service.events().insert(calendarId="primary", body=body).execute()
    return result["id"]


def delete_event(event_id: str) -> bool:
    """Delete an event from the primary calendar. Returns True on success."""
    try:
        _get_service().events().delete(calendarId="primary", eventId=event_id).execute()
        return True
    except Exception:
        logger.exception("delete_event failed for event %s", event_id)
        return False


def event_is_gone(event_id: str) -> bool | None:
    """Has this primary-calendar event been deleted/cancelled outside our control?

    Returns True if the event no longer exists (404/410) or is marked cancelled,
    False if it's still live, and None when we genuinely can't tell (auth error,
    network hiccup, transient API failure). Callers MUST treat None as "leave the
    row alone" — never flag a trip as deleted off an uncertain read.
    """
    try:
        from googleapiclient.errors import HttpError
    except Exception:
        HttpError = None  # type: ignore
    try:
        ev = (
            _get_service()
            .events()
            .get(calendarId="primary", eventId=event_id)
            .execute()
        )
        return ev.get("status") == "cancelled"
    except Exception as e:  # noqa: BLE001
        status = getattr(getattr(e, "resp", None), "status", None)
        if HttpError is not None and isinstance(e, HttpError) and status in (404, 410):
            return True
        return None


def _list_calendar_events(service, cal_id: str, time_min: str, time_max: str,
                          max_results: int = 2500) -> list[dict]:
    """Every event on `cal_id` in the window, paginated. A page-fetch failure
    stops pagination early and returns whatever pages already succeeded, same
    as the caller's old inline try/except-continue."""
    out: list[dict] = []
    page_token = None
    try:
        while True:
            result = (
                service.events()
                .list(
                    calendarId=cal_id, timeMin=time_min, timeMax=time_max,
                    maxResults=max_results, singleEvents=True,
                    orderBy="startTime", pageToken=page_token,
                )
                .execute()
            )
            out.extend(result.get("items", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break
    except Exception:
        logger.exception("fetch_events: failed listing events for calendar %s", cal_id)
    return out


def _events_to_trip_candidates(events: list[dict]) -> list[dict]:
    """Genuine multi-day trips (>= 2 nights) among `events`, deduplicated by id."""
    seen_ids = set()
    trips = []
    for ev in events:
        ev_id = ev.get("id", "")
        if ev_id in seen_ids:
            continue
        seen_ids.add(ev_id)
        start = ev.get("start", {})
        end_ev = ev.get("end", {})
        start_date = start.get("date") or start.get("dateTime", "")[:10]
        end_date = end_ev.get("date") or end_ev.get("dateTime", "")[:10]
        if not (start_date and end_date and end_date > start_date):
            continue
        try:
            days = (
                datetime.strptime(end_date, "%Y-%m-%d")
                - datetime.strptime(start_date, "%Y-%m-%d")
            ).days
        except ValueError:
            days = 0
        if days < 2:
            continue
        trips.append({
            "id": ev.get("id", ""),
            "summary": _detitle(ev.get("summary", "")) or "Unnamed Event",
            "location": ev.get("location", ""),
            "start_date": start_date,
            "end_date": end_date,
        })
    return trips


def _drop_contained_trips(trips: list[dict]) -> list[dict]:
    """Remove events fully contained within another event (sub-events, not
    top-level trips)."""
    return [
        ev
        for ev in trips
        if not any(
            other["start_date"] <= ev["start_date"]
            and other["end_date"] >= ev["end_date"]
            and other["id"] != ev["id"]
            for other in trips
        )
    ]


def fetch_events() -> list[dict]:
    """Fetch upcoming multi-day events from Google Calendar."""
    try:
        service = _get_service()
        now = datetime.utcnow().isoformat() + "Z"
        end = (datetime.utcnow() + timedelta(days=180)).isoformat() + "Z"
        cal_list = _calendars()

        events = []
        for cal in cal_list:
            events.extend(_list_calendar_events(service, cal["id"], now, end))

        trips = _events_to_trip_candidates(events)
        trips = _drop_contained_trips(trips)
        CACHE_FILE.write_text(json.dumps(trips, indent=2))
        return trips
    except Exception:
        logger.exception("fetch_events failed")
        return []


def _extract_url(description: str) -> str:
    """Pull the first meaningful URL from an HTML or plain-text event description."""
    skip = ("g.co/calendar", "mail.google.com", "google.com/calendar")
    for m in re.finditer(r'href=["\']([^"\']+)["\']', description):
        url = m.group(1)
        if url.startswith("http") and not any(s in url for s in skip):
            return url
    for m in re.finditer(r"https?://[^\s<>\"'&]+", description):
        url = m.group(0).rstrip(".,;)")
        if not any(s in url for s in skip):
            return url
    return ""


def _collect_range_events(service, cal_list: list[dict], time_min: str, time_max: str,
                          max_results: int) -> list[dict]:
    """Every event across `cal_list` in the window, deduplicated by id. A
    calendar whose listing fails is skipped, same as the caller's old inline
    try/except-continue."""
    all_events, seen = [], set()
    for cal in cal_list:
        try:
            result = (
                service.events()
                .list(
                    calendarId=cal["id"], timeMin=time_min, timeMax=time_max,
                    maxResults=max_results, singleEvents=True, orderBy="startTime",
                )
                .execute()
            )
        except Exception:
            logger.exception("fetch_sub_events: failed listing events for calendar %s", cal.get("id"))
            continue
        for ev in result.get("items", []):
            if ev["id"] not in seen:
                seen.add(ev["id"])
                all_events.append(ev)
    return all_events


def _sub_event_time(dt_str: str) -> str:
    if not dt_str:
        return ""
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%b %-d, %-I:%M") + ("a" if dt.hour < 12 else "p")
    except Exception:
        return dt_str[:16]


def _housing_from_description(description: str, location: str, title: str) -> dict | None:
    ci = re.search(r"check.?in:?\s*(.+)", description, re.IGNORECASE)
    co = re.search(r"check.?out:?\s*(.+)", description, re.IGNORECASE)
    if not (ci or co):
        return None
    conf = re.search(
        r"confirmation\s*(?:number|#|code)?:?\s*([^\n]+)", description, re.IGNORECASE,
    )
    lines = [ln.strip() for ln in description.strip().splitlines() if ln.strip()]
    hotel_name = lines[0] if lines else title
    return {
        "name": hotel_name,
        "address": location,
        "check_in": ci.group(1).strip() if ci else "",
        "check_out": co.group(1).strip() if co else "",
        "confirmation_code": conf.group(1).strip() if conf else "",
        "status": "booked",
    }


def _match_check_marker(title_l: str) -> str | None:
    """Check-in / check-out pairing (preserve event for URL extraction later)."""
    if re.search(r"\bcheck.?in\b", title_l):
        return "check_in"
    if re.search(r"\bcheck.?out\b", title_l):
        return "check_out"
    return None


def _match_flight(title: str, title_l: str, location: str, start_dt: str, end_dt: str,
                  start_d: str) -> dict | None:
    if not (re.search(r"\b[A-Z]{2}\s*\d{3,4}\b", title)
            or any(k in title_l for k in ["flight", "depart", "arrive", "airline"])):
        return None
    codes = re.findall(r"\b([A-Z]{3})\b", title)
    fnum_m = re.search(r"\b([A-Z]{2}\s*\d{3,4})\b", title)
    return {
        "direction": "return" if any(k in title_l for k in ["return", "back", "home"]) else "outbound",
        "flight_num": fnum_m.group(1).replace(" ", "") if fnum_m else title,
        "from_airport": codes[0] if codes else "",
        "to_airport": codes[1] if len(codes) > 1 else "",
        "departure_time": _sub_event_time(start_dt) or start_d,
        "arrival_time": _sub_event_time(end_dt) or "",
        "notes": location,
        "status": "booked",
    }


# Word-boundary match to avoid e.g. "bus" in "columbus".
_TRANSPORT_RE = re.compile(
    r"\b(shuttle|express|bus|train|transit|metro|ferry|uber|lyft|taxi|rideshare"
    r"|rental|pickup|pick.?up|car\s+pick|drop.?off|dropoff)\b",
    re.IGNORECASE,
)


def _transport_type(title_l: str) -> str:
    if any(k in title_l for k in ["rental", "pickup", "pick", "drop"]):
        return "car"
    if any(k in title_l for k in ["bus", "shuttle", "express"]):
        return "bus"
    if "train" in title_l:
        return "train"
    if "ferry" in title_l:
        return "ferry"
    if any(k in title_l for k in ["uber", "lyft", "taxi"]):
        return "rideshare"
    return "other"


def _match_transport(title: str, title_l: str, description: str, location: str,
                     start_dt: str, end_dt: str, start_d: str) -> dict | None:
    if not _TRANSPORT_RE.search(title):
        return None
    cost_m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", description)
    cost = float(cost_m.group(1).replace(",", "")) if cost_m else None
    return {
        "type": _transport_type(title_l),
        "description": title,
        "departure": _sub_event_time(start_dt) or start_d,
        "arrival": _sub_event_time(end_dt) or "",
        "notes": " | ".join(p for p in (description.split("\n")[0], location) if p),
        "cost": cost,
        "status": "booked",
    }


def _match_activity(is_all_day: bool, start_d: str, end_d: str, title: str,
                    location: str) -> dict | None:
    """Multi-day sub-events → decided activities (e.g. a festival)."""
    if not (is_all_day and end_d > start_d):
        return None
    try:
        days = (
            datetime.strptime(end_d, "%Y-%m-%d") - datetime.strptime(start_d, "%Y-%m-%d")
        ).days
    except Exception:
        days = 0
    if days < 1:
        return None
    return {"name": title, "location": location, "status": "decided"}


def _classify_sub_event(ev: dict, start_date: str) -> dict:
    """One event bucketed for fetch_sub_events. `kind` is one of housing,
    check_in, check_out, flight, transport, activity, or None (skip)."""
    title = _detitle(ev.get("summary", ""))
    title_l = title.lower()
    location = ev.get("location", "")
    description = ev.get("description", "") or ""
    start_info = ev.get("start", {})
    end_info = ev.get("end", {})
    start_d = start_info.get("date", "")
    start_dt = start_info.get("dateTime", "")
    end_d = end_info.get("date", "")
    end_dt = end_info.get("dateTime", "")
    is_all_day = bool(start_d and not start_dt)

    # Skip recurring work/personal events
    if any(k in title_l for k in ["shift", "birthday", "anniversary"]):
        return {"kind": None}

    # Main trip event (all-day, starts on trip start) — mine for hotel description
    if is_all_day and start_d == start_date:
        entry = _housing_from_description(description, location, title)
        return {"kind": "housing", "entry": entry} if entry else {"kind": None}

    marker = _match_check_marker(title_l)
    if marker:
        return {"kind": marker}

    flight = _match_flight(title, title_l, location, start_dt, end_dt, start_d)
    if flight:
        return {"kind": "flight", "entry": flight}

    transport = _match_transport(title, title_l, description, location, start_dt, end_dt, start_d)
    if transport:
        return {"kind": "transport", "entry": transport}

    activity = _match_activity(is_all_day, start_d, end_d, title, location)
    if activity:
        return {"kind": "activity", "entry": activity}

    return {"kind": None}


def _housing_from_check_events(check_in_ev: dict | None, check_out_ev: dict | None) -> dict:
    loc_ev = check_in_ev or check_out_ev
    assert loc_ev is not None  # guarded by the caller
    loc = loc_ev.get("location", "")
    url = _extract_url(loc_ev.get("description", "") or "")
    return {
        "name": loc.split(",")[0].strip() if loc else "Accommodation",
        "address": loc,
        "check_in": _sub_event_time((check_in_ev or {}).get("start", {}).get("dateTime", "")),
        "check_out": _sub_event_time((check_out_ev or {}).get("start", {}).get("dateTime", "")),
        "url": url,
        "status": "booked",
    }


def _enrich_housing_from_check_event(entry: dict, check_in_ev: dict | None,
                                     check_out_ev: dict | None) -> None:
    """Enrich from check-in event: address and URL."""
    ev_ref = check_in_ev or check_out_ev
    assert ev_ref is not None  # guarded by the caller
    check_loc = ev_ref.get("location", "")
    check_url = _extract_url(ev_ref.get("description", "") or "")
    if check_loc and not entry.get("address"):
        entry["address"] = check_loc
    if check_url and not entry.get("url"):
        entry["url"] = check_url


def _finalize_housing(housing: list[dict], check_in_ev: dict | None,
                      check_out_ev: dict | None) -> list[dict]:
    """Build housing from check-in/out if not already found in description."""
    if not housing and (check_in_ev or check_out_ev):
        housing.append(_housing_from_check_events(check_in_ev, check_out_ev))
    elif housing and (check_in_ev or check_out_ev):
        _enrich_housing_from_check_event(housing[0], check_in_ev, check_out_ev)
    return housing


def fetch_sub_events(start_date: str, end_date: str) -> dict:
    """Parse housing, flights, transport, activities from calendar events within a trip's date range."""
    try:
        service = _get_service()
        cal_list = _calendars()
        time_min = f"{start_date}T00:00:00Z"
        time_max = f"{end_date}T23:59:59Z"
        all_events = _collect_range_events(service, cal_list, time_min, time_max, 200)

        housing, flights, transportation, activities = [], [], [], []
        check_in_ev, check_out_ev = None, None

        for ev in all_events:
            res = _classify_sub_event(ev, start_date)
            kind = res["kind"]
            if kind == "housing":
                housing.append(res["entry"])
            elif kind == "check_in":
                check_in_ev = ev
            elif kind == "check_out":
                check_out_ev = ev
            elif kind == "flight":
                flights.append(res["entry"])
            elif kind == "transport":
                transportation.append(res["entry"])
            elif kind == "activity":
                activities.append(res["entry"])

        housing = _finalize_housing(housing, check_in_ev, check_out_ev)

        return {
            "housing": housing,
            "flights": flights,
            "transportation": transportation,
            "activities": activities,
        }
    except Exception:
        logger.exception("fetch_sub_events failed for range %s to %s", start_date, end_date)
        return {"housing": [], "flights": [], "transportation": [], "activities": []}


# --- Event labels (Google's 2026-06-17 expanded colors) -----------------------
#
# Google went from 11 event colors to 24. The 13 new ones are *labels* on the
# calendar resource and have no `colorId` at all, so `colorId` can no longer
# file an event into most of Sam's categories. A label is set with
# `eventLabelId` plus `eventLabelVersion=1`, and the installed client's static
# discovery doc predates that parameter, so the generated `.patch()` rejects it.
# The category -> label id map is mirrored in
# wiki/notes/calendar-event-conventions.md, which is read before every write.
#
# ponytail: one extra HTTP call per labelled event rather than rebuilding the
# service off a network-fetched discovery doc, which would add a fetch and a
# failure mode to every connector call. Revisit when the client ships the param.

EVENT_LABELS = {
    "Deadlines": "e0763ed9-3d16-4142-b416-b92542879bb8",
    "Admin + Money": "171357f9-8d22-4e1b-b33b-f5adc78e8d13",
    "Appointments + Interviews": "ea44ceb7-e64e-4d42-a6f7-15a08b933833",
    "Food": "bf78f509-21ce-4e03-8c86-977e1695b00c",
    "Trips": "6e985e84-7a25-4e5d-b085-6614a92cf5f0",
    "Errands": "4a7b123f-d2ca-4e23-8000-5a201df0f7ab",
    "Events": "67429cfe-6f83-408c-926d-7b4de5ae32dd",
    "Exercise": "4290f2ed-dc72-435a-96d6-36dbc70a8430",
    "Social": "a16f4cd5-4025-4a9b-8649-54b78c47052a",
    "Logistics": "0a05ab10-70d6-4d6c-b492-46c4c135b563",
    "Work Shifts": "3ee19e7d-e954-439f-9a30-1ed22cb03bbd",
    "Birthdays": "64fc3ad5-b3aa-4c49-a47b-82c4bc7d5bf0",
    "Flights + Transit": "d0347d5a-3a95-4376-8586-06c7ca613959",
    "Stays": "5cd9106d-7d85-4642-88b8-46077f4fe451",
}

_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events/{eid}"


def set_event_label(event_id: str, label: str, calendar_id: str = "primary") -> dict:
    """Put an existing event on one of Sam's named colors.

    `label` is a category name from EVENT_LABELS (e.g. "Work Shifts") or a raw
    label id. Google-generated events — contact birthdays, and events Gmail
    created from a confirmation — reject this with a 400 and always will; that
    is a permanent exception, not something to retry.
    """
    import requests
    from google.auth.transport.requests import Request

    label_id = EVENT_LABELS.get(label, label)
    # Refresh unconditionally: this connector does not persist token expiry, so a
    # disk-loaded credential reports valid while carrying an expired access token,
    # and the raw request 401s. The generated client hides this by refreshing on
    # every build; doing it by hand costs one round trip.
    creds = _load_creds()
    creds.refresh(Request())
    r = requests.patch(
        _EVENTS_URL.format(cal=calendar_id, eid=event_id),
        params={"eventLabelVersion": 1},
        json={"eventLabelId": label_id},
        headers={"Authorization": "Bearer " + creds.token},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def create_event(event_body: dict, calendar_id: str = "primary",
                 label: str | None = None) -> dict:
    """Create a new Google Calendar event. Returns the created event resource.

    `label` files the event on one of Sam's 24 named colors (see
    EVENT_LABELS). Pass it instead of a `colorId` for any category that lives on
    one of the 13 colors Google added in 2026 — those have no colorId at all.
    """
    result = (
        _get_service()
        .events()
        .insert(calendarId=calendar_id, body=event_body)
        .execute()
    )
    if label:
        result = set_event_label(result["id"], label, calendar_id)
    return result


def update_event(event_id: str, event_body: dict, calendar_id: str = "primary") -> dict:
    """Update an existing Google Calendar event. Returns the updated event resource."""
    result = (
        _get_service()
        .events()
        .update(calendarId=calendar_id, eventId=event_id, body=event_body)
        .execute()
    )
    return result


def snap_iso_to_5min(iso: str) -> str:
    """Round an ISO-8601 datetime to the nearest 5 minutes, zero the seconds, and
    keep the original UTC offset. Date-only strings (all-day events) pass through
    untouched. Two back-to-back events whose shared boundary was equal stay equal
    after snapping (same input → same output), so Google Calendar keeps rendering
    them as touching instead of overlapping — and the result matches the phone's
    5-minute time picker. See wiki/notes/calendar-event-conventions.md.
    """
    if "T" not in iso:  # all-day date — nothing to snap
        return iso
    dt = datetime.fromisoformat(iso)
    r = round(dt.minute / 5) * 5
    if r == 60:
        dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        dt = dt.replace(minute=r, second=0, microsecond=0)
    return dt.isoformat()


def min_chip_patches(events: list[dict], min_minutes: int = 15) -> list[dict]:
    """Detect + fix the sub-chip overlap: Google Calendar renders every event at a
    minimum height of `min_minutes`, so an event shorter than that draws a chip
    taller than its real duration and visually spills into whatever follows.

    Rule (Sam's): when a timed event is shorter than `min_minutes` AND another
    event starts inside its rendered chip (start < short.start + min_minutes),
    extend the short event's end to short.start + min_minutes and push the
    follower's start to that same mark, so the two touch cleanly. Cascades to a
    fixpoint (a pushed follower that becomes short is fixed in turn). Only the
    nearest strictly-later follower is moved (concurrent same-start events are
    left alone). Boundaries land on the 5-minute grid via snap_iso_to_5min.

    Input/return: lists of {'id','start','end'} with ISO datetimes. Returns only
    the events whose times changed. All-day rows (no 'T') are ignored.
    """
    timed = [e for e in events if "T" in e.get("start", "")]
    cur = [
        {
            "id": e["id"],
            "s": datetime.fromisoformat(e["start"]),
            "e": datetime.fromisoformat(e["end"]),
            "touched": False,
        }
        for e in timed
    ]
    cur.sort(key=lambda c: c["s"])
    delta = timedelta(minutes=min_minutes)
    changed = True
    while changed:
        changed = False
        for a in cur:
            if (a["e"] - a["s"]) >= delta:
                continue
            chip_end = a["s"] + delta
            # nearest strictly-later event that begins inside a's rendered chip
            follower = min(
                (b for b in cur if a["s"] < b["s"] < chip_end),
                key=lambda b: b["s"],
                default=None,
            )
            if follower is None:
                continue
            if a["e"] != chip_end:
                a["e"] = chip_end
                a["touched"] = changed = True
            if follower["s"] != chip_end:
                follower["s"] = chip_end
                if follower["e"] <= follower["s"]:
                    follower["e"] = follower["s"] + delta
                follower["touched"] = changed = True
    # Emit ONLY events the formula actually moved — never re-snap untouched events
    # (that would round real off-grid times like an 11:26 flight arrival).
    return [
        {
            "id": c["id"],
            "start": snap_iso_to_5min(c["s"].isoformat()),
            "end": snap_iso_to_5min(c["e"].isoformat()),
        }
        for c in cur
        if c["touched"]
    ]


def snap_event_body(body: dict) -> dict:
    """Snap an event body's start/end dateTime onto the 5-minute grid, in place
    (timed events only — all-day `date` fields and absent keys are left alone).
    Returns the same dict for chaining.

    Apply this at human/UI write points — the Hub create + schedule-edit
    endpoints and the voice-memo pipeline. Do NOT bake it into create_event /
    patch_event: flight and trip pushes go through those carrying real-world
    times (a 11:26 arrival must not become 11:25).
    """
    for key in ("start", "end"):
        slot = body.get(key)
        if isinstance(slot, dict) and slot.get("dateTime"):
            slot["dateTime"] = snap_iso_to_5min(slot["dateTime"])
    return body


def patch_event(event_id: str, fields: dict, calendar_id: str = "primary") -> dict:
    """Partially update an event — only the keys in `fields` change, the rest of
    the event is untouched. Use this to extend an event's end time without
    clobbering its summary/start/color (which a full update_event would wipe)."""
    result = (
        _get_service()
        .events()
        .patch(calendarId=calendar_id, eventId=event_id, body=fields)
        .execute()
    )
    return result


def fetch_events_window(days_back: int = 2, days_forward: int = 2) -> list[dict]:
    """Fetch events in a window spanning recent past → near future across all
    calendars. Unlike fetch_week_events (future-only), this includes already-
    finished events, so a placeholder created earlier today is still visible.
    Returns [{id, calendar_id, summary, color_id, location, start_dt, end_dt}].
    """
    try:
        service = _get_service()
        now = datetime.utcnow()
        time_min = (now - timedelta(days=days_back)).isoformat() + "Z"
        time_max = (now + timedelta(days=days_forward)).isoformat() + "Z"
        cal_list = _calendars()
        out, seen = [], set()
        for cal in cal_list:
            try:
                result = (
                    service.events()
                    .list(
                        calendarId=cal["id"],
                        timeMin=time_min,
                        timeMax=time_max,
                        maxResults=250,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )
            except Exception:
                logger.exception("fetch_events_window: failed listing events for calendar %s", cal.get("id"))
                continue
            for ev in result.get("items", []):
                if ev["id"] in seen:
                    continue
                seen.add(ev["id"])
                start, end = ev.get("start", {}), ev.get("end", {})
                out.append(
                    {
                        "id": ev.get("id", ""),
                        "calendar_id": cal["id"],
                        "summary": _detitle(ev.get("summary", "")),
                        "color_id": ev.get("colorId", ""),
                        "location": ev.get("location", ""),
                        "start_dt": start.get("dateTime", "") or start.get("date", ""),
                        "end_dt": end.get("dateTime", "") or end.get("date", ""),
                    }
                )
        return out
    except Exception:
        logger.exception(
            "fetch_events_window failed (days_back=%s, days_forward=%s)", days_back, days_forward
        )
        return []


def _batch_fetch_events(service, cal_list: list[dict], time_min: str, time_max: str) -> list[dict]:
    """Every calendar's events in the window, one batch HTTP request instead of
    one sequential events().list() per calendar (the old serial loop was the
    home page's dominant cost, ~1.2s; batching collapses it to one round-trip).
    request_id is the calendar's index (a plain string) to keep the batch
    Content-ID free of '@'/'.' from cal ids. Dedup keeps the first calendar's
    copy of a shared event, iterating cal_list in order (matches the old serial
    behavior)."""
    results: dict[str, list] = {}

    def _collect(request_id: str, response: dict, exception) -> None:
        if exception is None and response is not None:
            results[request_id] = response.get("items", [])

    batch = service.new_batch_http_request(callback=_collect)
    for idx, cal in enumerate(cal_list):
        req = service.events().list(
            calendarId=cal["id"], timeMin=time_min, timeMax=time_max,
            maxResults=50, singleEvents=True, orderBy="startTime",
        )
        # The static discovery doc lacks eventLabelVersion (see EVENT_LABELS);
        # without it events come back with no eventLabelId.
        req.uri += "&eventLabelVersion=1"
        batch.add(req, request_id=str(idx))
    batch.execute()

    labels = _label_colors(service)
    events, seen_ids = [], set()
    for idx, cal in enumerate(cal_list):
        for ev in results.get(str(idx), []):
            if ev["id"] not in seen_ids:
                seen_ids.add(ev["id"])
                ev["_cal_id"] = cal["id"]
                # The color Google draws it in: its label, else its calendar's.
                cal_bg = cal.get("backgroundColor", "")
                ev["_color"] = labels.get(ev.get("eventLabelId", ""), _MODERN.get(cal_bg.lower(), cal_bg))
                events.append(ev)
    return events


# calendarList still reports a calendar's color in the classic pastel palette;
# Google's UI draws the modern equivalent (the same 24 hexes the labels use).
# A custom color has no entry and passes through as-is.
_MODERN = {
    "#ac725e": "#795548", "#d06b64": "#e67c73", "#f83a22": "#d50000", "#fa573c": "#f4511e",
    "#ff7537": "#ef6c00", "#ffad46": "#f09300", "#42d692": "#009688", "#16a765": "#0b8043",
    "#7bd148": "#7cb342", "#b3dc6c": "#c0ca33", "#fbe983": "#e4c441", "#fad165": "#f6bf26",
    "#92e1c0": "#33b679", "#9fe1e7": "#039be5", "#9fc6e7": "#4285f4", "#4986e7": "#3f51b5",
    "#9a9cff": "#7986cb", "#b99aff": "#b39ddb", "#c2c2c2": "#616161", "#cabdbf": "#a79b8e",
    "#cca6ac": "#ad1457", "#f691b2": "#d81b60", "#cd74e6": "#8e24aa", "#a47ae2": "#9e69af",
}

_label_cache: tuple[float, dict] | None = None


def _label_colors(service) -> dict:
    """label id -> hex, from the primary calendar's labelProperties. Same TTL
    as the calendar list; an empty map on failure so events fall back to their
    calendar color."""
    global _label_cache
    if _label_cache and time.monotonic() - _label_cache[0] < _CAL_TTL:
        return _label_cache[1]
    try:
        req = service.calendars().get(calendarId="primary")
        req.uri += ("&" if "?" in req.uri else "?") + "eventLabelVersion=1"
        labels = {lb["id"]: lb.get("backgroundColor", "")
                  for lb in (req.execute().get("labelProperties") or {}).get("eventLabels", [])}
    except Exception:
        logger.exception("_label_colors: calendars.get failed")
        return {}
    _label_cache = (time.monotonic(), labels)
    return labels


def _fmt_clock(dt_str: str) -> str:
    """Lowercase a/p, no space: the hub's one clock shape. Every reader of this
    string parses "([ap])?m?" so a payload cached in the old "9:00am" spelling
    still plots correctly."""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        hr = dt.hour % 12 or 12
        ampm = "a" if dt.hour < 12 else "p"
        return f"{hr}:{dt.minute:02d}{ampm}"
    except Exception:
        return dt_str[11:16]


def _week_event_link(ev: dict, description: str) -> str:
    """"Smart" website link: prefer a URL the event actually carries — a
    Meet/conference video link, else the first http(s) URL in the description
    — and fall back to the event's own Google Calendar page (htmlLink always
    exists). location stays separate: it drives the maps deep-link, not the
    website click."""
    link = ev.get("hangoutLink", "") or ""
    if link:
        return link
    for ep in (ev.get("conferenceData", {}) or {}).get("entryPoints", []) or []:
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return ep["uri"]
    m_url = re.search(r"https?://\S+", description)
    if m_url:
        return m_url.group(0).rstrip(").,;>\"'")
    return ev.get("htmlLink", "") or ""


def _week_event_row(ev: dict) -> dict:
    title = _detitle(ev.get("summary", ""))
    start = ev.get("start", {})
    start_date = start.get("date") or start.get("dateTime", "")[:10]
    start_dt = start.get("dateTime", "")
    all_day = bool(start.get("date"))
    time_str = _fmt_clock(start_dt) if start_dt else "all day"

    end = ev.get("end", {})
    # End time, formatted to match time_str. Timed events only — all-day
    # events have no clock end, and Google's all-day "end" is the
    # exclusive next-day date, which is meaningless to show here.
    end_dt_raw = end.get("dateTime", "")
    time_end_str = _fmt_clock(end_dt_raw) if (end_dt_raw and not all_day) else ""

    description = ev.get("description", "") or ""
    link = _week_event_link(ev, description)

    return {
        "date": start_date,
        "time": time_str,
        "time_end": time_end_str,
        # Proper case preserved in the data; the dashboard lowercases
        # for display via CSS only (never saved back to Google Calendar).
        "summary": title,
        "all_day": all_day,
        "color_id": ev.get("colorId", ""),
        "color": ev.get("_color", ""),
        "id": ev.get("id", ""),
        "calendar_id": ev.get("_cal_id", "primary"),
        "description": description,
        "location": _relocate(ev.get("location", "")),
        "link": link,
        "start_dt": start_dt or start.get("date", ""),
        "end_dt": end.get("dateTime", "") or end.get("date", ""),
    }


def fetch_week_events(days: int = 7, days_back: int = 0) -> list[dict]:
    """Fetch all calendar events in the window for the Hub schedule panel.

    Spans `days_back` days into the past through `days` days forward. days_back
    defaults to 0 (future-only, the original behavior); pass 1 to include
    yesterday so the schedule can render a past day.
    Returns [{date, time, summary, all_day, id, calendar_id, description, start_dt, end_dt}].
    Skips holidays and recurring noise (birthdays, anniversaries). Deduplicates across calendars.
    """
    try:
        service = _get_service()
        now = datetime.utcnow()
        time_min = (now - timedelta(days=days_back)).isoformat() + "Z"
        time_max = (now + timedelta(days=days)).isoformat() + "Z"
        cal_list = _calendars()

        events = _batch_fetch_events(service, cal_list, time_min, time_max)
        out = [_week_event_row(ev) for ev in events]

        # Sort by ISO start: an all-day start_dt ("2026-05-31") sorts ahead of
        # any timed start_dt ("2026-05-31T09:00…") on the same date, and timed
        # events fall into true chronological order (the old key compared the
        # display time string lexically, so "10:00am" sorted before "9:00am").
        out.sort(key=lambda e: (e["date"], e["start_dt"]))
        return out
    except Exception:
        logger.exception("fetch_week_events failed (days=%s, days_back=%s)", days, days_back)
        return []


def get_cached_events() -> list[dict]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            logger.debug("get_cached_events: cache file unreadable, treating as empty",
                         exc_info=True)
    return []


# --- task completion marker (edit-in-place, never delete/recreate) ---

_DONE_PREFIX = "✓ "  # "✓ "
_COMPLETED_RE = re.compile(r"^Completed \d{4}-\d{2}-\d{2}\s*$", re.MULTILINE)


def mark_event_complete(event_id: str, calendar_id: str, done_date: str) -> bool:
    """Mark a calendar event done in place: prepend a checkmark to the title and
    ensure a 'Completed YYYY-MM-DD' line sits at the top of the description.
    Never deletes or recreates the event. Returns True on success."""
    try:
        service = _get_service()
        cal = calendar_id or "primary"
        ev = service.events().get(calendarId=cal, eventId=event_id).execute()

        # Raw, NOT _detitle'd: this branch writes the title back to the calendar, and
        # decoding here would silently rewrite someone else's event text as a side
        # effect of ticking it off. Decoding is for display only.
        title = ev.get("summary", "") or ""
        if not title.startswith(_DONE_PREFIX):
            ev["summary"] = _DONE_PREFIX + title

        desc = ev.get("description", "") or ""
        desc = _COMPLETED_RE.sub("", desc).lstrip("\n")
        ev["description"] = f"Completed {done_date}" + (
            f"\n\n{desc}" if desc.strip() else ""
        )

        service.events().update(calendarId=cal, eventId=event_id, body=ev).execute()
        return True
    except Exception:
        logger.exception(
            "mark_event_complete failed for event %s on calendar %s", event_id, calendar_id
        )
        return False


def unmark_event_complete(event_id: str, calendar_id: str) -> bool:
    """Reverse mark_event_complete: strip the checkmark prefix and remove the
    'Completed YYYY-MM-DD' line. Returns True on success."""
    try:
        service = _get_service()
        cal = calendar_id or "primary"
        ev = service.events().get(calendarId=cal, eventId=event_id).execute()

        title = ev.get("summary", "") or ""   # raw: written back, see mark_event_complete
        if title.startswith(_DONE_PREFIX):
            ev["summary"] = title[len(_DONE_PREFIX) :]

        desc = ev.get("description", "") or ""
        ev["description"] = _COMPLETED_RE.sub("", desc).lstrip("\n")

        service.events().update(calendarId=cal, eventId=event_id, body=ev).execute()
        return True
    except Exception:
        logger.exception(
            "unmark_event_complete failed for event %s on calendar %s", event_id, calendar_id
        )
        return False
