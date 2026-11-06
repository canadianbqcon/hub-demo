"""What's actually around a place — the walkable scope, not the nearest anything.

Overpass (OpenStreetMap) answers "what is within N metres of this pin", which is
the whole question a stay's map can't answer on its own. Deliberately NOT a
"nearest pharmacy" search: a nearest-match with no radius will happily report a
CVS four miles down a highway as if that were a fact worth having. Outside the
radius the honest answer is nothing, and that is what this returns.

Same OSM data the tiles already come from, so no key, no billing, no new
dependency. The price is that OSM has no ratings — there is no "good" signal in
the data at all. The one quality proxy it does carry is `brand`/`brand:wikidata`,
which marks a chain, so every result says whether it is local or not and links
out for the review read.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "ObsidianVaultDashboard/1.0 (personal use; demo@example.com)"

# The immediacy radius. ~15 min of crow-flies walking, or about two minutes of
# in-town driving — the point past which "it's nearby" stops being true.
# ponytail: one radius for every place. A dense city block and a Colorado
# cul-de-sac genuinely have different walk sheds; if that matters, make it a
# per-trip field rather than guessing from population density here.
RADIUS_M = 1200
CACHE_PATH = Path(__file__).resolve().parent / "nearby_cache.json"
CACHE_TTL_SEC = 30 * 86400          # a corner shop does not move in a month
PER_CATEGORY = 3                     # how many named results each headline category keeps

_lock = threading.Lock()
_last_call = 0.0
# Overpass is not Nominatim. The public instance hands out ~2 slots per IP on a
# rolling budget, and 1.1 s (copied from the geocoder's floor) blows through it
# inside three stays — the failures were 429s, not bad queries.
MIN_INTERVAL_SEC = 4.0
# 504 means the free instance is at capacity, 429 means we are over quota. Both
# clear on their own, so they are worth waiting out rather than surfacing. One
# lookup is therefore up to ~20 s of retry before it gives up, which only ever
# happens on the first look at an address — after that the month-long cache
# answers instantly.
RETRY_STATUS = (429, 504)
RETRY_BACKOFF = (2, 5, 12)

# Category → the OSM tag values that land in it, in priority order. The first
# five are the headline read (always rendered, even empty, because "there is no
# pharmacy near this house" is itself the answer someone came for). The rest are
# a footnote, shown only when they exist.
HEADLINE = ["coffee", "food", "drinks", "groceries", "pharmacy"]
EXTRA = ["cash", "gas", "laundry", "park"]

_AMENITY = {
    "cafe": "coffee", "ice_cream": "coffee",
    "restaurant": "food", "fast_food": "food",
    "bar": "drinks", "pub": "drinks", "biergarten": "drinks",
    "pharmacy": "pharmacy",
    "atm": "cash", "bank": "cash",
    "fuel": "gas",
}
_SHOP = {
    "coffee": "coffee", "bakery": "coffee",
    "supermarket": "groceries", "grocery": "groceries", "convenience": "groceries",
    "greengrocer": "groceries", "deli": "groceries", "butcher": "groceries",
    "alcohol": "groceries", "wine": "groceries",
    "chemist": "pharmacy",
    "laundry": "laundry", "dry_cleaning": "laundry",
}
_LEISURE = {"park": "park"}

# Per category, the OSM tag values that only repeat the heading back.
_SAYS_NOTHING = {
    "coffee": ("cafe", "coffee"), "pharmacy": ("pharmacy", "chemist"),
    "cash": ("bank", "atm"), "gas": ("fuel",), "park": ("park",),
    "laundry": ("laundry",), "food": ("restaurant",), "drinks": ("bar", "pub"),
}

_QUERY = """[out:json][timeout:30];
(
  nwr(around:{r},{lat},{lng})["amenity"~"^({amenities})$"];
  nwr(around:{r},{lat},{lng})["shop"~"^({shops})$"];
  nwr(around:{r},{lat},{lng})["leisure"="park"];
);
out center tags;"""


def _throttle() -> None:
    global _last_call
    with _lock:
        delta = time.monotonic() - _last_call
        if delta < MIN_INTERVAL_SEC:
            time.sleep(MIN_INTERVAL_SEC - delta)
        _last_call = time.monotonic()


def _metres(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Crow-flies, equirectangular. Over 1.2 km the great-circle correction is
    centimetres, and the number is about to be inflated by a detour factor
    anyway — a haversine here would be precision theatre."""
    x = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return math.hypot(x, y) * 6371000


def _walk_min(metres: float) -> int:
    """Straight-line metres → walking minutes. 1.35 for the fact that streets are
    not straight, 80 m/min for the fact that people are not fast."""
    return max(1, round(metres * 1.35 / 80))


def _classify(tags: dict) -> str | None:
    return (_AMENITY.get(tags.get("amenity", ""))
            or _SHOP.get(tags.get("shop", ""))
            or _LEISURE.get(tags.get("leisure", "")))


def _is_chain(tags: dict) -> bool:
    """OSM's own chain flag. Ceiling: it is only as good as the mapper — a Wendy's
    in San Salvador carries no `brand` tag and reads as local here. Upgrade path
    is a brand-name list, which is unbounded maintenance for a hint; the name on
    the row already tells a human what it is.
    """
    return bool(tags.get("brand") or tags.get("brand:wikidata"))


def _fetch(lat: float, lng: float, radius: int) -> list[dict]:
    """One Overpass call, retried through the server's own busy signals.

    Deliberately no mirror fallback. The two busiest alternates 504'd on the same
    query, and overpass.osm.ch answered in a second with zero results because it
    only serves a Switzerland extract — a fallback that silently reports "nothing
    nearby" for every address on earth is worse than the error it replaces.
    """
    q = _QUERY.format(
        r=radius, lat=lat, lng=lng,
        amenities="|".join(sorted(_AMENITY)),
        shops="|".join(sorted(_SHOP)),
    )
    for attempt, wait in enumerate((*RETRY_BACKOFF, None)):
        _throttle()
        req = urllib.request.Request(
            OVERPASS_URL,
            data=urllib.parse.urlencode({"data": q}).encode(),
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode()).get("elements", [])
        except urllib.error.HTTPError as e:
            # A 400 is our query being wrong and will fail identically forever;
            # only the load signals are worth waiting out.
            if e.code not in RETRY_STATUS or wait is None:
                raise
            logger.info("overpass %s, retry %s in %ss", e.code, attempt + 1, wait)
        except (urllib.error.URLError, TimeoutError) as e:
            if wait is None:
                raise
            logger.info("overpass unreachable (%s), retry %s in %ss", e, attempt + 1, wait)
        time.sleep(wait)
    raise RuntimeError("unreachable")  # the loop's last pass always returns or raises


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(cache))
    except Exception as e:  # a cache that can't write is slow, not broken
        logger.warning("nearby cache write failed: %s", e)


def _shape(elements: list[dict], lat: float, lng: float, radius: int) -> dict:
    """Overpass elements → {category: [place, ...]}, nearest first.

    Unnamed rows are dropped: "there is a restaurant 300 m away" with no name is
    not something anyone can act on, and OSM carries a lot of them.
    """
    buckets: dict[str, list[dict]] = {k: [] for k in HEADLINE + EXTRA}
    seen: set[tuple[str, str]] = set()
    for e in elements:
        tags = e.get("tags") or {}
        name = (tags.get("name") or "").strip()
        cat = _classify(tags)
        if not name or not cat:
            continue
        plat = e.get("lat", (e.get("center") or {}).get("lat"))
        plng = e.get("lon", (e.get("center") or {}).get("lon"))
        if plat is None or plng is None:
            continue
        d = _metres(lat, lng, plat, plng)
        if d > radius:          # `around` is generous on ways; re-check the centre
            continue
        # The same shop mapped as both a node and a building way is one shop.
        key = (cat, name.lower())
        if key in seen:
            continue
        seen.add(key)
        kind = (tags.get("cuisine", "").split(";")[0]
                or tags.get("shop", "") or tags.get("amenity", "")).replace("_", " ")
        buckets[cat].append({
            "name": name,
            # "cafe" under coffee and "chemist" under pharmacy are the heading said
            # twice. "supermarket" vs "convenience" under groceries is not — that
            # is the difference between a shop and a corner store.
            "kind": "" if kind in _SAYS_NOTHING.get(cat, ()) else kind,
            "chain": _is_chain(tags),
            "metres": round(d),
            "walk_min": _walk_min(d),
            "lat": plat, "lng": plng,
        })
    for rows in buckets.values():
        rows.sort(key=lambda p: p["metres"])
    return buckets


def nearby(lat: float, lng: float, radius: int = RADIUS_M, refresh: bool = False) -> dict:
    """Everything worth knowing within `radius` of a pin.

    Returns {"radius_m", "walk_min", "headline": [{cat, places}], "extra": [{cat, place}]}.
    Lists, not dicts, because the order IS information (coffee before a laundromat)
    and Flask's jsonify sorts dict keys alphabetically underneath you.

    A headline category with nothing in range comes back with an empty `places`,
    on purpose — the caller renders that as "nothing this close" rather than
    reaching further out for something to say.
    """
    key = f"{round(lat, 4)},{round(lng, 4)},{radius}"
    cache = _load_cache()
    hit = cache.get(key)
    if hit and not refresh and time.time() - hit.get("at", 0) < CACHE_TTL_SEC:
        return hit["data"]

    elements = _fetch(lat, lng, radius)
    buckets = _shape(elements, lat, lng, radius)
    data = {
        "radius_m": radius,
        "walk_min": _walk_min(radius),
        "headline": [{"cat": c, "places": buckets[c][:PER_CATEGORY]} for c in HEADLINE],
        # The footnote row only ever needs the closest one of each.
        "extra": [{"cat": c, "place": buckets[c][0]} for c in EXTRA if buckets[c]],
    }
    cache[key] = {"at": time.time(), "data": data}
    _save_cache(cache)
    return data


if __name__ == "__main__":  # ponytail: one self-check, no framework
    assert _walk_min(0) == 1, "a zero-distance place still reads as a minute, never 0"
    assert _walk_min(800) == 14, _walk_min(800)
    assert 1100 < _metres(30.24, -97.78, 30.25, -97.78) < 1120, _metres(30.24, -97.78, 30.25, -97.78)
    assert _classify({"amenity": "cafe"}) == "coffee"
    assert _classify({"shop": "bakery"}) == "coffee"
    assert _classify({"amenity": "parking"}) is None
    assert _is_chain({"brand": "CVS Pharmacy"}) and not _is_chain({"name": "Joe's"})

    here = (30.240803, -97.7791878)
    els = [
        {"lat": here[0] + 0.001, "lon": here[1], "tags": {"name": "Joe's", "amenity": "cafe"}},
        {"lat": here[0] + 0.001, "lon": here[1], "tags": {"name": "Joe's", "amenity": "cafe"}},
        {"lat": here[0] + 0.0005, "lon": here[1], "tags": {"name": "CVS", "amenity": "pharmacy",
                                                           "brand": "CVS Pharmacy"}},
        {"lat": here[0] + 0.05, "lon": here[1], "tags": {"name": "Far Cafe", "amenity": "cafe"}},
        {"lat": here[0], "lon": here[1], "tags": {"amenity": "cafe"}},          # unnamed
    ]
    b = _shape(els, here[0], here[1], RADIUS_M)
    assert [p["name"] for p in b["coffee"]] == ["Joe's"], b["coffee"]   # deduped, far one dropped
    assert b["pharmacy"][0]["chain"] is True
    assert b["drinks"] == []
    print("nearby.py self-check ok")
