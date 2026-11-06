"""Interest matching (keyword overlap against a trip's activities) and the
/food research bridge, scoped to a trip's destination city.

Split from trips/api.py (Task 4 of the 2026-09-24 trips-split plan; this
sub-file split out of the first draft of api_places.py, which came in over
500 lines by itself). Reaches every trips.api global through the `_api`
alias and every trips.db function through `db`, both by attribute at call
time (never `from .api import ...` / `from .db import ...`), so a test's
monkeypatch on either facade still lands here — `_api._food_ready` is
patched by name in the test suite (test_trips_food_tab.py), which is why
`_food_db` writes it through as `_api._food_ready` rather than owning a
local module global. See dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

import contextlib
import json
import re

from flask import current_app, jsonify, request

from . import api as _api
from . import db


# ── Interest matching (keyword / token — no model call) ───────────────────────

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "at", "with",
    "some", "any", "i", "we", "want", "like", "love", "see", "do", "go", "visit",
    "something", "stuff", "things", "thing", "good", "nice", "really", "more",
    "that", "this", "is", "are", "be", "my", "our", "me", "us",
}


def _tokenize(text: str) -> list[str]:
    return [
        t for t in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(t) >= 3 and t not in _STOPWORDS
    ]


def _activity_haystack(a: dict) -> str:
    tags = a.get("tags") or ""
    if isinstance(tags, str):
        with contextlib.suppress(Exception):
            parsed = json.loads(tags)
            tags = " ".join(str(t) for t in parsed) if isinstance(parsed, list) else tags
    parts = [a.get("name", ""), a.get("location", ""), str(tags), a.get("description", "")]
    return " ".join(p for p in parts if p).lower()


@_api.bp.route("/api/trips/<int:trip_id>/interests/analyze", methods=["POST"])
def api_analyze_interest(trip_id: int):
    """Match a free-form interest to activities by keyword overlap (no API key)."""
    data = request.get_json(force=True, silent=True) or {}
    raw = (data.get("input") or "").strip()
    if not raw:
        return jsonify({"error": "input required"}), 400

    trip = db.get_full_trip(trip_id)
    if not trip:
        return jsonify({"error": "trip not found"}), 404
    activities = trip.get("activities") or []

    tokens = set(_tokenize(raw))
    matched = []
    if tokens:
        for a in activities:
            hay = _activity_haystack(a)
            if any(tok in hay for tok in tokens):
                matched.append(a["id"])

    words = [w for w in raw.split() if w]
    label = " ".join(words[:5]) if words else raw
    return jsonify({"label": label, "matched_ids": matched})


# ── Food (the /food research, scoped to this trip's area) ────────────────────
#
# The trip board shows the food research for wherever the trip goes. It reads
# food.db directly rather than linking to the /food module, for one reason: the
# public mirror registers the trips blueprint and NOTHING else, so /food does not
# exist over there and a link to it is a dead end for every guest.
#
# Reading it here also makes the scope right by construction. The route below
# takes a trip id, not an area — a caller cannot ask for an area this trip is not
# in, so what leaves the mirror is the one city the guest is already going to and
# never the rest of the research.
#
# GET only, on both surfaces. The /food skill is the only writer of that database
# and nothing here may change that.


def _food_db():
    """The food module's own db layer, initialised on first use.

    Lazily, because Hub initialises it when it registers the food blueprint and
    the mirror never registers it at all — so the mirror would otherwise reach an
    uninitialised module. Importing is safe on both: it is a module import, not a
    blueprint registration, so no /food route comes with it.

    `_api._food_ready` (not a local global) — Rule 1: the flag is facade state, and
    test_trips_food_tab.py monkeypatches it on `trips.api` directly.
    """
    from food import db as fdb

    if not _api._food_ready:
        fdb.init(_api._VAULT_ROOT / "data" / "food.db")
        _api._food_ready = True
    return fdb


def _trip_area(trip: dict):
    """The researched area this trip goes to, or None.

    Matched on the city name appearing in the trip's destination or its name,
    longest city first. Trips carry a free-text destination ("Denver, CO",
    "Hyatt Regency Columbus, Columbus") and no city column, so there is nothing
    more structured to join on.

    Longest-first matters the moment two researched cities share a prefix — "York"
    inside "New York" is the shape of it. Substring, not token, because a
    destination writes cities as "Santa Tecla / San Salvador" as readily as it
    writes "Denver, CO".

    A miss is a normal answer, not an error: most trips go somewhere nobody has
    researched yet.
    """
    fdb = _food_db()
    hay = fdb.fold(f"{trip.get('destination') or ''} {trip.get('name') or ''}")
    if not hay.strip():
        return None
    cities = [a for a in fdb.get_areas() if a.get("level") == "city"]
    cities.sort(key=lambda a: len(a.get("city") or ""), reverse=True)
    for area in cities:
        city = fdb.fold(area.get("city") or "")
        if city and city in hay:
            # Resolved rather than returned raw: resolve_area attaches the `member`
            # tuple, and the shared renderer reads that to know which places belong to
            # which child area. Without it this payload is a near-copy of the /food
            # one, and a near-copy is what the two surfaces are being pulled out of.
            return fdb.resolve_area(area["slug"]) or area
    return None


@_api.bp.route("/api/trips/<int:trip_id>/food", methods=["GET"])
def api_trip_food(trip_id):
    """The food research for this trip's city: the area, its places, its boroughs.

    `area` is None when nothing has been researched where this trip goes, which is
    the common case and is what the tab's empty state renders. Returning 200 with
    a null area rather than 404 keeps "no research yet" distinct from "no such
    trip" — the tab has different things to say about each.
    """
    trip = db.get_trip(trip_id)
    if not trip:
        return jsonify({"error": "not found"}), 404
    area = _trip_area(trip)
    if area is None:
        return jsonify({"area": None, "places": [], "children": []})
    fdb = _food_db()
    return jsonify({
        "area": area,
        "places": fdb.get_places(city=area["city"]),
        "children": fdb.get_children(area),
        # Hub can open the full research; the mirror has no /food to open, and
        # saying so here keeps that decision out of the template.
        "portal": None if current_app.config.get("GUEST", False) else f"/food/{area['slug']}",
    })


@_api.bp.route("/api/trips/<int:trip_id>/food/place/<path:slug>", methods=["GET"])
def api_trip_food_place(trip_id, slug):
    """One place, with its evidence ledger — the read behind a row on the food tab.

    Scoped the same way the list is, and for the same reason: the route takes a trip
    id, works out that trip's city, and refuses anything outside it. A guest holding
    a slug off some other city's research gets the same 404 as a slug that does not
    exist, so the endpoint cannot be used to walk the database a place at a time.

    GET only. The /food skill is the only writer of that database.
    """
    trip = db.get_trip(trip_id)
    if not trip:
        return jsonify({"error": "not found"}), 404
    area = _trip_area(trip)
    if area is None:
        return jsonify({"error": "not found"}), 404
    fdb = _food_db()
    place = fdb.get_place(slug)
    # fold(), not ==: the city on a place row and the city on an area row are both
    # authored text, and "New York" has to match "new york".
    if place is None or fdb.fold(place.get("city")) != fdb.fold(area.get("city")):
        return jsonify({"error": "not found"}), 404
    place["evidence"] = fdb.get_evidence(place["id"])
    return jsonify(place)


