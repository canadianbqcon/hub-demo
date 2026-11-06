"""Transit routing: the self-hosted MOTIS proxy behind the day-of "Getting
there" card's Transit tab.

Split from trips/api.py (Task 4 of the 2026-09-24 trips-split plan; this
sub-file split out of the first draft of api_places.py, which came in over
500 lines by itself). Reaches every trips.api global through the `_api`
alias, same rule as every other section (never `from .api import ...`). No
`trips.db` calls here — a transit itinerary is public timetable data with no
trip in the request at all. `_drops_token_hop`, `_leg_pt` and `_stop_name`
stay importable from `trips.api` (the facade's bottom re-export block covers
this file the same way it covers every other section). See
dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from flask import jsonify, request

from . import api as _api


# ── TRANSIT ROUTING ────────────────────────────────────────────────────────────
# The Transit tab of the day-of "Getting there" card used to draw a straight
# dashed line, because nothing on this box could answer "which trains".
#
# It goes through this server-side proxy rather than the browser for two reasons,
# and both of them are the funnel. The router listens on this machine's loopback,
# so a guest's browser on a shared link has nothing to reach; and a public host in
# the mirror's connect-src would be a second thing to keep in sync with a second
# thing to trust. Proxied, the mirror's CSP stays at 'self' and the guest gets the
# same answer Sam does.
#
# api.transitous.org runs this same engine and answers the same query, but their
# usage policy asks that the consuming project be open source and vault-code is
# private, so the engine is self-hosted instead.
#
# Setup, the re-import procedure, and the bus-timetable horizon that WILL come up:
# MOTIS.md, beside this file. Read it before debugging an empty or wrong-dated
# Transit tab — the usual answer is a data refresh, not a code change.
_MOTIS_URL = os.environ.get("MOTIS_URL", "http://127.0.0.1:8080")
_RIDE_TZ = "America/New_York"

# Which of MOTIS's leg modes are a vehicle you board vs. the walk between them.
_TRANSIT_MODES = {
    "TRANSIT", "TRAM", "SUBWAY", "FERRY", "AIRPLANE", "BUS", "COACH", "RAIL",
    "HIGHSPEED_RAIL", "LONG_DISTANCE", "NIGHT_RAIL", "REGIONAL_FAST_RAIL",
    "REGIONAL_RAIL", "METRO", "CABLE_CAR", "FUNICULAR", "AREAL_LIFT", "OTHER",
}


def _local_min(stamp) -> int | None:
    """A router timestamp as minutes past local midnight, or None.

    Computed here rather than in the browser because here is where the zone is
    known. The card's other clocks are all minutes-past-midnight run through
    T.fmtClock, so a train time arrives in the same shape as the rest of them and
    a guest reading the page from another country still sees the airport's clock.
    """
    try:
        d = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")) \
            .astimezone(ZoneInfo(_RIDE_TZ))
        return d.hour * 60 + d.minute
    except Exception:  # noqa: BLE001 - a missing time just goes unlabelled
        return None


def _decode_polyline(s: str, precision: int = 5) -> list:
    """Google's encoded-polyline format → [[lat, lng], ...].

    Fifteen lines of stdlib against a dependency for a format that has not changed
    since 2005. MOTIS states its own `precision` per leg, so it is a parameter
    rather than the 5 everyone hardcodes — theirs is 7.
    """
    out, lat, lng, i, factor = [], 0, 0, 0, float(10 ** precision)
    while i < len(s):
        for is_lat in (True, False):
            shift, result = 0, 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lat:
                lat += d
            else:
                lng += d
        # Five decimals is about a metre, which is finer than a route line drawn at
        # city zoom can show. The router emits seven, and the extra two doubled the
        # response — an N-train leg alone is 541 points, and a guest pulls the whole
        # thing over the funnel.
        out.append([round(lat / factor, 5), round(lng / factor, 5)])
    return out


# The MTA ships route colours in its feeds, and they are NOT the colours on the
# signs. Two separate problems:
#
#   * The subway feed carries a MUTED variant of the palette — #F6BC26 where the N
#     is really #FCCC0A, #EB6800 where the F is #FF6319, #799534 where the G is
#     #6CBE45. Close enough to look intentional, wrong enough to look off.
#   * The bus feeds assign each route one of seven rotating colours that mean
#     nothing to a rider AND collide with the subway. The B43 comes back #EE352E —
#     the 1/2/3 red — so a bus draws itself on the map as a train.
#
# Subway lines are therefore keyed to the MTA's own published palette. Verified
# 2026-08-28 against web.mta.info/developers/resources/line_colors.htm and the
# mta-colors dataset, which agree on every entry used here.
_SUBWAY_COLORS = {
    "1": "#EE352E", "2": "#EE352E", "3": "#EE352E",
    "4": "#00933C", "5": "#00933C", "6": "#00933C",
    "7": "#B933AD",
    "A": "#0039A6", "C": "#0039A6", "E": "#0039A6",
    "B": "#FF6319", "D": "#FF6319", "F": "#FF6319", "M": "#FF6319",
    "G": "#6CBE45",
    "J": "#996633", "Z": "#996633",
    "L": "#A7A9AC",
    "N": "#FCCC0A", "Q": "#FCCC0A", "R": "#FCCC0A", "W": "#FCCC0A",
    "S": "#808183", "H": "#808183", "FS": "#808183", "GS": "#808183",
    "SI": "#0039A6", "SIR": "#0039A6",
}
# Every bus is one colour, deliberately. There is no such thing as a recognisable
# bus colour — nobody knows "the B43 colour", the number on the front is the
# identity — so a per-route colour buys nothing and costs the one thing that
# matters here, which is that a bus must not wear a subway line's red. The MTA's
# own bus blue, and no subway line uses it.
_BUS_COLOR = "#00AEEF"


def _line_color(mode: str, short_name: str | None, feed_color: str | None) -> str:
    """The colour a rider would recognise, not the one the feed happens to carry."""
    name = (short_name or "").strip().upper()
    if mode == "SUBWAY":
        # 6X / 7X are the express runs of the same line, same colour as the local.
        base = name[:-1] if len(name) > 1 and name.endswith("X") else name
        return _SUBWAY_COLORS.get(base) or _SUBWAY_COLORS.get(name) or "#808183"
    if mode in ("BUS", "COACH"):
        return _BUS_COLOR
    # Rails and everything else keep what the feed says — the LIRR and Metro-North
    # branch colours in their feeds ARE the published ones.
    c = (feed_color or "").strip()
    if not c:
        return ""
    return c if c.startswith("#") else "#" + c


def _stop_name(raw) -> str:
    """A stop name the way it is written on the sign, not the way the feed shouts it.

    The subway feed writes "Bergen St". The BUS feeds write "74 ST/ROOSEVELT AV
    STATION" — every bus stop in the MTA's bus GTFS is upper case. Side by side on
    the map those read as two different kinds of thing, and the caps one reads as
    an error. Title-cased ONLY when the name has no lower case in it at all, so a
    correctly-cased name is never re-cased (which would turn "JFK" into "Jfk").
    """
    name = (raw or "").strip()
    if name and not any(c.islower() for c in name):
        # Per LETTER RUN, not per space-delimited word: the bus feed's names hinge
        # on slashes and dashes ("74 ST/ROOSEVELT AV", "HOYT-SCHERMERHORN"), and
        # splitting on spaces alone leaves "74 St/roosevelt Av". A letter run also
        # does the right thing with an apostrophe, which str.title() does not.
        return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), name)
    return name


def _leg_pt(end: dict | None):
    """A leg endpoint as [lat, lng], or None if the router did not place it."""
    if end is None:
        return None
    try:
        return [round(float(end["lat"]), 5), round(float(end["lon"]), 5)]
    except (TypeError, KeyError, ValueError):
        return None


def _transit_leg(leg: dict) -> dict:
    """One MOTIS leg, trimmed to what the card draws.

    The full leg carries fare products, alerts, per-stop times and the rental
    fields — a few KB each, none of it on screen. What the card needs is the line's
    name, its official colour, when it leaves, when it lands and the shape to draw.
    """
    geo = leg.get("legGeometry") or {}
    mode = leg.get("mode") or ""
    return {
        "mode": mode,
        "transit": mode in _TRANSIT_MODES,
        # routeShortName is the roundel: "F", "Q70-SBS", "M60-SBS". headsign is the
        # direction it is pointed, which is how you know it is the right platform.
        "line": (leg.get("routeShortName") or "").strip(),
        "headsign": (leg.get("headsign") or "").strip(),
        "agency": (leg.get("agencyName") or "").strip(),
        # Normalised to the palette on the signs — see _line_color.
        "color": _line_color(mode, leg.get("routeShortName"), leg.get("routeColor")),
        "from": _stop_name((leg.get("from") or {}).get("name")),
        "to": _stop_name((leg.get("to") or {}).get("name")),
        # Where you board and where you get off, as coordinates, so the map can
        # put a named mark there. Without these the walk to the station is a
        # dashed line ending in mid-block with nothing saying which door it is.
        "from_pt": _leg_pt(leg.get("from")),
        "to_pt": _leg_pt(leg.get("to")),
        "start": leg.get("startTime"),
        "end": leg.get("endTime"),
        "start_min": _local_min(leg.get("startTime")),
        "end_min": _local_min(leg.get("endTime")),
        "dur": leg.get("duration"),
        "line_pts": _decode_polyline(geo["points"], geo.get("precision", 5))
                    if geo.get("points") else [],
    }


# A bus you ride for one minute is not a bus anyone rides. The router offers them
# because they are, on its own arithmetic, a few seconds quicker than the same walk
# — and a New Yorker reading "walk 7, B57 for 1 min, walk 3" stops trusting the card.
_TOKEN_HOP_S = 180          # a boarding this short is a rounding error, not a ride
_TOKEN_HOP_MODES = {"BUS", "COACH", "TRAM"}


def _drops_token_hop(itineraries: list) -> list:
    """Drop itineraries whose only contribution is a sub-3-minute bus hop.

    Only ever drops one when a cleaner itinerary came back in the same answer and
    is NO SLOWER. That is the whole test: if the token hop is genuinely buying
    time, it survives; if walking the same stretch lands you there at the same
    moment or sooner, the hop was noise and goes. Nothing is reordered and nothing
    is invented — an answer with no clean alternative is returned untouched, which
    is the honest outcome when the hop really is the only way.
    """
    def token(it):
        return any(leg["transit"] and leg["mode"] in _TOKEN_HOP_MODES
                   and (leg["dur"] or 0) < _TOKEN_HOP_S for leg in it["legs"])

    clean = [it for it in itineraries if not token(it)]
    if not clean:
        return itineraries
    best = min((it["dur"] or 0) for it in clean)
    return [it for it in itineraries if not token(it) or best > (it["dur"] or 0)]


def _transit_point(name: str) -> str | None:
    raw = (request.args.get(name) or "").split(",")
    try:
        return "%.6f,%.6f" % (float(raw[0]), float(raw[1]))
    except (ValueError, IndexError):
        return None


def _transit_query(frm: str, to: str) -> tuple[dict, str]:
    """The MOTIS query params, plus the raw `time` string (for the staleness check)."""
    q = {
        "fromPlace": frm,
        "toPlace": to,
        "arriveBy": "true" if request.args.get("arriveBy") in ("1", "true") else "false",
        # More than the card shows: the token-hop rule below drops itineraries,
        # and it can only drop one if a walk-instead alternative came back with it.
        "numItineraries": "6",
        "transitModes": "TRANSIT",
    }
    # The card's clock times are NAIVE — "04:30" on a date, the way the itinerary
    # was typed — and the router refuses a time with no zone on it (verified: a
    # bare `2026-08-31T13:00:00` answers "missing parameter"). So the zone is put
    # on here, where zoneinfo already knows when the clocks changed, rather than in
    # the browser where it would mean parsing a formatted Intl string.
    #
    # ponytail: one zone constant, because every airport this board departs from is
    #   in it. An airport -> tz column is the upgrade the first non-Eastern
    #   departure needs; a wrong offset would move the leave-by by an hour, so it
    #   should not be guessed from the browser's own zone (a guest reading this
    #   from another country would get their offset, not the airport's).
    when = (request.args.get("time") or "").strip()
    if when:
        try:
            naive = datetime.datetime.fromisoformat(when.replace("Z", "")[:19])
            q["time"] = naive.replace(tzinfo=ZoneInfo(_RIDE_TZ)).isoformat()
        except Exception:  # noqa: BLE001 - an unparseable time means "now"
            _api.logger.warning("transit: could not read time %r, using now", when)
    return q, when


def _build_itineraries(data: dict) -> list:
    out = []
    for it in (data.get("itineraries") or []):
        legs = [_transit_leg(leg) for leg in (it.get("legs") or [])]
        out.append({
            "start": it.get("startTime"),
            "end": it.get("endTime"),
            "start_min": _local_min(it.get("startTime")),
            "end_min": _local_min(it.get("endTime")),
            "dur": it.get("duration"),
            # Transfers as the reader counts them: how many times you get off one
            # vehicle and onto another, which is one fewer than the vehicles.
            "transfers": max(0, len([leg for leg in legs if leg["transit"]]) - 1),
            "walk": it.get("walkDistance"),
            "legs": legs,
        })
    return out


def _transit_staleness(when: str, out: list) -> dict:
    """`{"stale_for": ..., "asked_for": ...}` when the router answered for the
    wrong day, or `{}` when the answer matches (or nothing was asked).

    THE ANSWER MAY NOT BE FOR THE DAY THAT WAS ASKED, and it does not say so.

    Past the end of the timetable the router does not answer empty — it answers
    with the last day it has, dated that day, with no flag on it. Ask for a
    flight three weeks out and you get a plausible set of trains for a Saturday
    in the past, which is the worst possible failure for a card someone reads to
    catch a plane: it looks exactly like a real answer.

    The horizon is the BUS feeds. The MTA publishes those about ten weeks at a
    time (all seven end 2026-09-05 as imported), while subway runs to October and
    the commuter rails into November. No subway reaches LGA, so every trip to
    that airport ends on a bus and inherits the earliest horizon on the board.
    Re-running the import once the MTA publishes the next window is the fix, and
    it is a data refresh, not a code change.

    Both dates are read in the RIDE's zone, not UTC. An evening flight leaves on
    one UTC date and lands on the next, so comparing the raw Z strings would call
    a perfectly good 9pm answer stale.
    """
    asked = when[:10]
    got = ""
    if out and out[0].get("end"):
        try:
            got = (datetime.datetime.fromisoformat(out[0]["end"].replace("Z", "+00:00"))
                   .astimezone(ZoneInfo(_RIDE_TZ)).date().isoformat())
        except Exception:  # noqa: BLE001 - an unreadable stamp just skips the check
            got = ""
    if asked and got and asked != got:
        return {"stale_for": got, "asked_for": asked}
    return {}


_MOTIS_DATA = os.path.expanduser(os.environ.get("MOTIS_DATA", "~/motis/data"))
_FEED_ENDS: dict = {}


def _feed_end(path: str) -> str:
    """Last service day (YYYY-MM-DD) in one GTFS zip, cached per file mtime."""
    import csv, io, zipfile  # noqa: E401 - only this check needs them
    key = (path, os.path.getmtime(path))
    if key not in _FEED_ENDS:
        days = []
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            for f, col in (("calendar.txt", "end_date"), ("calendar_dates.txt", "date")):
                if f in names:
                    days += [r[col] for r in csv.DictReader(io.TextIOWrapper(z.open(f), "utf-8-sig"))]
        d = max(days) if days else ""
        _FEED_ENDS[key] = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d else ""
    return _FEED_ENDS[key]


def _ended_feeds(asked: str) -> list:
    """The feeds whose timetable ends before the day asked.

    The whole-answer check above misses ONE feed running out while the others
    keep going: on 2026-11-01 the subway feed ended and the bus feeds ran to
    January, so the router answered a 75-minute four-bus ride to Chrystie St,
    correctly dated, where the F takes 20 minutes. Feeds that never matter to the
    city card (PATH, dead since June) are skipped. Fix is a re-import (MOTIS.md).
    """
    out = []
    for name in ("gtfs_subway", "gtfs_b", "gtfs_m", "gtfs_q", "gtfs_bx"):
        p = os.path.join(_MOTIS_DATA, name + ".zip")
        try:
            end = _feed_end(p)
        except Exception:  # noqa: BLE001 - no data dir on this machine: no check
            continue
        if asked and end and asked > end:
            out.append({"feed": name, "ended": end})
    return out


@_api.bp.route("/api/transit")
def api_transit():
    """Real transit itineraries between two points, from the self-hosted router.

    A read with no subject, like the address search above: two coordinates in,
    public timetable data out. Nothing here is scoped to a member, so it is safe
    on the mirror, and the mirror's own session gate still fronts it.

    Answers 200 with an empty list rather than an error whenever the router is
    down, cold, or has nothing for the day asked. The tab's straight dashed line is
    a working fallback — an error banner over a card someone is reading at 4am to
    catch a plane is worse than the line it replaced.

    `arriveBy` is the point of the whole thing: the reader does not want a train
    leaving now, they want the last one that still lands before bag drop.
    """
    frm, to = _transit_point("from"), _transit_point("to")
    if not frm or not to:
        return jsonify({"itineraries": [], "error": "need from and to as lat,lng"}), 400
    q, when = _transit_query(frm, to)
    url = _MOTIS_URL + "/api/v1/plan?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - the tab degrades to the dashed line
        _api.logger.warning("transit plan failed (%s): %s", url, e)
        return jsonify({"itineraries": [], "error": "router unavailable"})
    # Shortest trip first, and THAT is what the card leads with.
    #
    # arriveBy hands back the last departures that still land before bag drop, and
    # the router's own order is by that departure — so the first three were the
    # three latest starts, not the three quickest trips. A 62-minute slog and a
    # 42-minute ride both make the plane; only one of them is worth an answer, and
    # the card was picking by which left later. Ranked by total door-to-door
    # duration the three on screen are the three shortest the timetable offers,
    # which is what "best route" means when every option already arrives in time.
    out = sorted(_drops_token_hop(_build_itineraries(data)), key=lambda it: it.get("dur") or 0)[:3]
    stale = _transit_staleness(when, out)
    ended = _ended_feeds(when[:10] if when else datetime.date.today().isoformat())
    return jsonify({"itineraries": out, **stale, **({"feeds_ended": ended} if ended else {})})
