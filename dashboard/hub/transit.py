"""Subway state for the home page's "getting there" card.

Two feeds, both keyless:
  - MTA subway alerts (GTFS-realtime as JSON, ~1MB, ~200 entities, most of them
    planned work for other days). Cached 5 minutes.
  - MTA Stations.csv from data.ny.gov (68KB; Stop Name, Daytime Routes, lat/lon).
    Cached on disk beside home-last-good.json and never re-fetched once present.

An alert matters only if it touches a stop on the actual trip -- the destination
station, or the nearest station to where he is starting from on a line that
reaches it -- in the direction of travel. The start is `origin()` (see below) and
the boarding stop is picked per reaching line, matching "whichever line takes me
there best". Untagged alerts (~57% carry no direction) always pass. This replaces
the old whole-line watch, which surfaced every disruption anywhere on F/G/4/5.
Destinations arrive as the free-text calendar locations and are geocoded through
dashboard/geocode.py (Nominatim, 1.1s throttle), so the per-address result is
memoised for the life of the process.

The ordered trains and buses BETWEEN the two ends are not computed here -- the
card asks the self-hosted MOTIS router for those through /trips/api/transit,
which already exists for the trips board (see trips/MOTIS.md). This module's job
is the two endpoints and the alerts touching them.
"""
from __future__ import annotations

import csv
import io
import json
import math
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import geocode
from vault_path import vault_root

HOME_LINES = ["F", "G", "4", "5"]
# The door he actually leaves from, not the zip. A zip-level anchor put the
# boarding stop wherever Nominatim centred 11231, which is a few blocks off and
# picks a different first train.
HOME_ADDRESS = "100 Example Street, Brooklyn, NY 11201"
ALERTS_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts.json"
STATIONS_URL = "https://data.ny.gov/api/views/39hk-dx4f/rows.csv?accessType=DOWNLOAD"
STATIONS_PATH = Path(__file__).parent.parent / "mta-stations.csv"
TRIPS_DB = vault_root() / "data" / "trips.db"
ALERT_TTL = 300

_lock = threading.Lock()
_stations: list[dict] | None = None
_alerts: tuple[float, list[dict]] | None = None
_geo: dict[str, tuple[float, float] | None] = {}


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": geocode.USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def stations() -> list[dict]:
    global _stations
    if _stations is not None:
        return _stations
    if not STATIONS_PATH.exists():
        STATIONS_PATH.write_bytes(_get(STATIONS_URL))
    out = []
    for row in csv.DictReader(io.StringIO(STATIONS_PATH.read_text(encoding="utf-8"))):
        try:
            out.append({
                "id": row["GTFS Stop ID"],
                "name": row["Stop Name"],
                "lines": row["Daytime Routes"].split(),
                "lat": float(row["GTFS Latitude"]),
                "lng": float(row["GTFS Longitude"]),
            })
        except (KeyError, ValueError):
            continue
    _stations = out
    return out


def nearest_station(lat: float, lng: float) -> dict | None:
    # ponytail: linear scan over ~500 rows, per destination; a KD-tree if it ever shows up in a profile
    best, best_d = None, math.inf
    for s in stations():
        d = geocode.miles_between((lat, lng), (s["lat"], s["lng"]))
        if d < best_d:
            best, best_d = s, d
    if best is None:
        return None
    return {**best, "miles": round(best_d, 2)}


def nearest_station_on_line(lat: float, lng: float, line: str) -> dict | None:
    best, best_d = None, math.inf
    for s in stations():
        if line not in s["lines"]:
            continue
        d = geocode.miles_between((lat, lng), (s["lat"], s["lng"]))
        if d < best_d:
            best, best_d = s, d
    return best


def _geocode(query: str) -> tuple[float, float] | None:
    q = query.strip()
    if q not in _geo:
        try:
            _geo[q] = geocode.geocode(q)
        except Exception:
            _geo[q] = None
    return _geo[q]


def origin(today: str = "") -> dict:
    """Where he is starting from right now: his own door, or the place he is staying.

    Home is HOME_ADDRESS. It is overridden for the length of a trip by that trip's
    BOOKED housing, because on those days the walk to the first train starts at the
    hotel and a route drawn from Brooklyn is not a route he can take. Only `booked`
    counts -- a trip carries every place that was ever considered, and routing from
    a hostel he did not book would be worse than routing from home.

    Falls all the way back to home coordinates on any database or geocode trouble:
    an unroutable card is worse than one that assumes he slept in his own bed.
    """
    today = today or datetime.now().strftime("%Y-%m-%d")
    row = None
    try:
        con = sqlite3.connect(f"file:{TRIPS_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT h.name, h.address, h.lat, h.lng, t.name AS trip FROM housing h "
            "JOIN trips t ON t.id = h.trip_id "
            "WHERE h.status = 'booked' AND h.address <> '' "
            "  AND t.start_date <> '' AND t.end_date <> '' "
            "  AND t.start_date <= ? AND t.end_date >= ? "
            "ORDER BY t.start_date LIMIT 1", (today, today)).fetchone()
        con.close()
    except Exception:  # noqa: BLE001 - no trips db, no trip; home is the answer
        row = None

    if row:
        pt = (row["lat"], row["lng"]) if row["lat"] and row["lng"] else _geocode(row["address"])
        if pt:
            return {"label": row["name"] or row["address"], "address": row["address"],
                    "lat": pt[0], "lng": pt[1], "trip": row["trip"] or ""}

    pt = _geocode(HOME_ADDRESS)
    return {"label": "home", "address": HOME_ADDRESS,
            "lat": pt[0] if pt else None, "lng": pt[1] if pt else None, "trip": ""}


def alerts() -> list[dict]:
    """Every alert active right now or starting before midnight tonight, deduped by text."""
    global _alerts
    with _lock:
        if _alerts and time.monotonic() - _alerts[0] < ALERT_TTL:
            return _alerts[1]
        try:
            feed = json.loads(_get(ALERTS_URL))
        except Exception:
            return _alerts[1] if _alerts else []
        now = time.time()
        eod = datetime.now().replace(hour=23, minute=59, second=59).timestamp()
        out, seen = [], set()
        for ent in feed.get("entity", []):
            al = ent.get("alert") or {}
            periods = al.get("active_period") or []
            live = not periods or any(
                p.get("start", 0) <= now and (not p.get("end") or p["end"] >= now) for p in periods)
            upcoming = None
            if not live:
                starts = [p["start"] for p in periods if now < p.get("start", 0) <= eod]
                if not starts:
                    continue
                upcoming = min(starts)
            try:
                text = al["header_text"]["translation"][0]["text"]
            except (KeyError, IndexError, TypeError):
                continue
            if text in seen:
                continue
            seen.add(text)
            ies = al.get("informed_entity", [])
            out.append({
                "lines": sorted({ie.get("route_id") for ie in ies if ie.get("route_id")}),
                # selectors: (route, stop, direction) — direction is None when the feed omits it
                "sel": [(ie.get("route_id"), ie.get("stop_id"), ie.get("direction_id")) for ie in ies],
                "text": text,
                "type": (al.get("transit_realtime.mercury_alert") or {}).get("alert_type", ""),
                "starts": int(upcoming) if upcoming else None,
                # the windows still ahead today, so the card can keep only the ones that
                # overlap his ride (2026-10-21 mark); [] = no stated window, always on
                "periods": [[int(p.get("start", 0)), int(p["end"]) if p.get("end") else None]
                            for p in periods
                            if p.get("start", 0) <= eod and (not p.get("end") or p["end"] >= now)],
            })
        _alerts = (time.monotonic(), out)
        return out


def _want(relevant: dict[str, set[int]], stop_id: str | None, direction: int | None) -> None:
    """relevant[stop_id] = set of acceptable direction_ids; empty set means "any
    direction". An untagged alert entry (direction None) always passes."""
    if not stop_id:
        return
    dirs = relevant.setdefault(stop_id, set())
    if direction is not None:
        dirs.add(direction)


def _watch(watched: list[str], line: str) -> None:
    if line not in watched:
        watched.append(line)


def _scope_destination(
    q: str, home_pt: tuple[float, float] | None,
    relevant: dict[str, set[int]], watched: list[str],
) -> dict:
    """One destination's pin + nearest station, expanding `relevant`/`watched`
    in place to cover its boarding stops."""
    pt = _geocode(q)
    st = nearest_station(*pt) if pt else None
    dest = {
        "query": q,
        "lat": pt[0] if pt else None,
        "lng": pt[1] if pt else None,
        "station": st["name"] if st else None,
        "lines": st["lines"] if st else [],
    }
    if not st:
        return dest
    # ponytail: travel direction from a latitude sign, not a stop-sequence lookup.
    # NYCT direction_id 0 = north/uptown, 1 = south/downtown. Coarse but enough to drop
    # the clearly-wrong-direction half; untagged alerts still pass. Upgrade to a real
    # per-line stop order only if this misclassifies in practice.
    trip_dir = (0 if st["lat"] >= home_pt[0] else 1) if home_pt else None
    _want(relevant, st["id"], trip_dir)
    for ln in st["lines"]:
        _watch(watched, ln)
        if home_pt:
            hb = nearest_station_on_line(home_pt[0], home_pt[1], ln)
            if hb:
                _want(relevant, hb["id"], trip_dir)
    return dest


def _home_area_scope(home_pt: tuple[float, float], relevant: dict[str, set[int]], watched: list[str]) -> None:
    """No trips today: still scope to home-area boarding stops rather than whole lines."""
    for ln in HOME_LINES:
        _watch(watched, ln)
        hb = nearest_station_on_line(home_pt[0], home_pt[1], ln)
        if hb:
            _want(relevant, hb["id"], None)


def _hits_trip(a: dict, relevant: dict[str, set[int]], riding: list[str]) -> bool:
    if set(a["lines"]) & set(riding):
        return True
    for _route, stop, direction in a["sel"]:
        if stop in relevant:
            dirs = relevant[stop]
            if not dirs or direction is None or direction in dirs:
                return True
    return False


def _trip_alerts(relevant: dict[str, set[int]], riding: list[str], watched: list[str]) -> list[dict]:
    if relevant or riding:
        return [a for a in alerts() if _hits_trip(a, relevant, riding)]
    # geocode unavailable: fall back to the old whole-line watch so nothing is hidden.
    for ln in HOME_LINES:
        _watch(watched, ln)
    return [a for a in alerts() if set(a["lines"]) & set(watched)]


def view(destinations: list[str], riding: list[str] | None = None, day: str = "") -> dict:
    """What the card renders: where he is starting from, the lines in play, each
    destination's pin + nearest station, and only the alerts that touch a stop on
    the actual trip (boarding stop + destination stop) in the direction of travel.

    Trip = origin() -> each destination. The boarding stop is chosen per line
    reaching the destination, matching "whichever line takes me there". The
    origin's coordinates go out with the payload because the card feeds them
    straight to the router for the actual trains and buses.

    `riding` is those lines once the card has them back -- the subway lines the
    router actually put him on. A line he is RIDING is watched end to end, with no
    stop or direction filter: the trip uses the whole segment between two stops
    this module does not model, so a delay anywhere on it is his delay. That is
    tighter than the old whole-line watch, not looser -- that one guessed four
    lines from a zip code, this one names the two or three he is on. The
    nearest-station scope below still runs, and still carries the answer on the
    first paint, before any route has come back.
    """
    riding = [ln for ln in (riding or []) if ln]
    org = origin(day)  # `day`: a later day starts from where he is staying that day
    home_pt = (org["lat"], org["lng"]) if org["lat"] is not None else None

    relevant: dict[str, set[int]] = {}
    watched: list[str] = []

    dests = []
    for q in destinations:
        if not q or not q.strip():
            continue
        dests.append(_scope_destination(q, home_pt, relevant, watched))

    if not relevant and home_pt:
        _home_area_scope(home_pt, relevant, watched)

    for ln in riding:
        _watch(watched, ln)

    hits = _trip_alerts(relevant, riding, watched)

    return {"origin": org, "watched": watched, "destinations": dests, "alerts": hits,
            "stops": sorted(relevant), "fetched": int(time.time() * 1000)}


# Google's own transit routes for the card (2026-11-07 mark: "can we just use the
# google recommended routes? why is it suggesting bus when its like an 8 minute
# walk"). The self-hosted router put him on the M15 for the last stretch from
# Delancey; Google walks it, which is what he does. Same itinerary shape the card
# already draws from /trips/api/transit, so the card only swaps its URL.
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
ROUTES_MASK = ",".join([
    "routes.duration",
    "routes.legs.steps.travelMode",
    "routes.legs.steps.staticDuration",
    "routes.legs.steps.transitDetails.headsign",
    "routes.legs.steps.transitDetails.stopDetails",
    "routes.legs.steps.transitDetails.transitLine.nameShort",
    "routes.legs.steps.transitDetails.transitLine.name",
    "routes.legs.steps.transitDetails.transitLine.color",
    "routes.legs.steps.transitDetails.transitLine.vehicle.type",
])
_routes_cache: dict[str, tuple[float, list]] = {}


def _secs(s: str | None) -> int:
    return int(float((s or "0s").rstrip("s") or 0))


def _local(ts: str) -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))


def _shape_route(r: dict) -> dict | None:
    """One Google route as the card's itinerary: consecutive walk steps merged into
    one walk leg, each ride a leg with its line, colour and stops."""
    from trips.api_transit import _line_color
    legs: list[dict] = []
    for st in (r.get("legs") or [{}])[0].get("steps") or []:
        dur = _secs(st.get("staticDuration"))
        td = st.get("transitDetails")
        if st.get("travelMode") != "TRANSIT" or not td:
            if legs and not legs[-1]["transit"]:
                legs[-1]["dur"] += dur
            else:
                legs.append({"mode": "WALK", "transit": False, "dur": dur})
            continue
        ln = td.get("transitLine") or {}
        sd = td.get("stopDetails") or {}
        mode = ((ln.get("vehicle") or {}).get("type") or "TRANSIT").upper()
        mode = "SUBWAY" if mode in ("SUBWAY", "METRO_RAIL") else mode
        short = (ln.get("nameShort") or ln.get("name") or "").strip()
        dep, arr = _local(sd["departureTime"]), _local(sd["arrivalTime"])
        legs.append({
            "mode": mode, "transit": True, "line": short,
            "headsign": (td.get("headsign") or "").strip(),
            "color": _line_color(mode, short, ln.get("color")) or "#808183",
            "from": (sd.get("departureStop") or {}).get("name", ""),
            "to": (sd.get("arrivalStop") or {}).get("name", ""),
            "dur": int((arr - dep).total_seconds()),
            "start_min": dep.hour * 60 + dep.minute, "end_min": arr.hour * 60 + arr.minute,
        })
    rides = [lg for lg in legs if lg["transit"]]
    if not rides:
        return None  # a walk-only answer is drawn from Google's WALK route instead (_walk_route)
    # Leave = first boarding minus the walk to it; land = last alighting plus the walk off.
    first, last = legs.index(rides[0]), legs.index(rides[-1])
    walk_in = sum(lg["dur"] for lg in legs[:first]) // 60
    walk_out = -(-sum(lg["dur"] for lg in legs[last + 1:]) // 60)
    start, end = rides[0]["start_min"] - walk_in, rides[-1]["end_min"] + walk_out
    return {"start_min": start, "end_min": end, "dur": (end - start) * 60,
            "transfers": len(rides) - 1, "legs": legs}


def google_routes(frm: str, to: str, arrive: str = "") -> list | None:
    """Up to three Google transit routes from `frm` to `to` ("lat,lng"), arriving
    by `arrive` (naive local ISO, the event start) or leaving now. None on any
    failure, so the caller can fall back to the self-hosted router."""
    import os
    import sys
    from zoneinfo import ZoneInfo
    sys.path.insert(0, os.path.expanduser("~/.config/vault-api"))
    try:
        from services import PLACES_API_KEY  # pyright: ignore[reportAttributeAccessIssue]
    except Exception:
        return None
    key = f"{frm}|{to}|{arrive}"
    hit = _routes_cache.get(key)
    if hit and time.time() - hit[0] < ALERT_TTL:
        return hit[1]

    def pt(s: str) -> dict:
        lat, lng = (float(x) for x in s.split(","))
        return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}

    try:
        body: dict = {"origin": pt(frm), "destination": pt(to), "travelMode": "TRANSIT",
                      "computeAlternativeRoutes": True}
    except ValueError:
        return None
    if arrive:
        try:
            at = datetime.fromisoformat(arrive[:19]).replace(tzinfo=ZoneInfo("America/New_York"))
            if at.timestamp() > time.time() + 60:
                body["arrivalTime"] = at.isoformat()
        except ValueError:
            pass
    req = urllib.request.Request(ROUTES_URL, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": PLACES_API_KEY,
        "X-Goog-FieldMask": ROUTES_MASK})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except Exception:
        return None
    out = [x for x in (_shape_route(r) for r in data.get("routes") or []) if x]
    # Google's own order: its first route is the one it recommends, and the card shows
    # only that one until he expands (2026-11-07 send-back).
    walk = _walk_route(pt(frm), pt(to), body.get("arrivalTime"), out, PLACES_API_KEY)
    if walk:
        out.insert(0, walk)
    _routes_cache[key] = (time.time(), out)
    return out


WALK_LEADS_MIN = 20  # ponytail: fixed cutoff; a walk this short or faster than the ride leads


def _walk_route(o: dict, d: dict, arrival: str | None, rides: list, api_key: str) -> dict | None:
    """Google's walk-only route as an itinerary, when it is short or beats every ride
    (2026-11-07 mark: "why is it suggesting bus when its like an 8 minute walk").
    Transit mode never answers walk-only, so this is its own WALK request."""
    req = urllib.request.Request(ROUTES_URL, data=json.dumps(
        {"origin": o, "destination": d, "travelMode": "WALK"}).encode(), headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            secs = _secs(((json.load(resp).get("routes") or [{}])[0]).get("duration"))
    except Exception:
        return None
    mins = -(-secs // 60)
    if not secs or (mins > WALK_LEADS_MIN and any(r["dur"] <= secs for r in rides)):
        return None
    if arrival:
        a = datetime.fromisoformat(arrival)
        end = a.hour * 60 + a.minute
        start = end - mins
    else:
        n = datetime.now(_local("2000-01-01T00:00:00Z").tzinfo)
        start = n.hour * 60 + n.minute
        end = start + mins
    return {"start_min": start, "end_min": end, "dur": mins * 60, "transfers": 0,
            "legs": [{"mode": "WALK", "transit": False, "dur": secs}]}


if __name__ == "__main__":
    # smallest check that fails if the plumbing breaks: a real Brooklyn pin lands
    # on a station carrying one of the home lines and carries a GTFS Stop ID, and
    # every alert the trip filter keeps actually touches a stop on the trip.
    st = nearest_station(40.6862, -73.9908)  # Bergen St (F G)
    assert st and st["id"] and set(st["lines"]) & {"F", "G"}, st
    o = origin("1900-01-01")  # a date inside no trip: must be the home door
    assert o["label"] == "home" and o["lat"] and o["lng"], o
    assert geocode.miles_between((o["lat"], o["lng"]), (40.6865, -73.9985)) < 0.2, o
    v = view(["Union Square, New York, NY"])
    assert v["origin"]["lat"] and v["destinations"][0]["station"], v
    # a line he is riding is watched whole, even with no stop of its own on the trip
    r = view(["Union Square, New York, NY"], riding=["7"])
    assert "7" in r["watched"], r["watched"]
    assert all(set(a["lines"]) & set(r["watched"]) for a in r["alerts"]), r["alerts"]
    stops = set(v["stops"])
    assert stops, v  # a real destination must produce trip stops to filter on
    for a in v["alerts"]:
        assert any(s in stops for _r, s, _d in a["sel"]), a
    print("ok", st["name"], "->", v["destinations"][0]["station"],
          "| trip-scoped:", len(v["alerts"]), "of", len(alerts()), "total alerts")
