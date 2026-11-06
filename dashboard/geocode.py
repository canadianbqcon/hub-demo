from __future__ import annotations

import logging
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "ObsidianVaultDashboard/1.0 (personal use; demo@example.com)"
MIN_INTERVAL_SEC = 1.1

_lock = threading.Lock()
_last_call = 0.0


def _clean(query: str) -> str:
    # Strip trailing parenthetical notes, em/en-dash suffixes, and a "-> somewhere
    # else" destination, all of which confuse Nominatim. A hike named
    # "Bear Lake Trailhead -> Lake Haiyaha" is searchable by where it starts.
    q = re.split(r"\s+(?:[—–-]|->|→)\s+", query, maxsplit=1)[0]
    # `\)?` because the dash split above runs first and can cut the closing paren
    # off: "1695 Platte St, Denver, CO 80202 (mobile food truck — this is a base
    # address)" splits at the em-dash and leaves "(mobile food truck" hanging on
    # the end, which Nominatim then matches nothing for.
    q = re.sub(r"\s*\([^)]*\)?\s*$", "", q).strip()
    # Strip prefix label before street number: "Trailhead, 2201 Barton..." -> "2201 Barton..."
    m = re.match(r"^[^,]+,\s*(\d+\s+.*)$", q)
    if m:
        q = m.group(1).strip()
    return q


_DIR = r"(?:N|S|E|W|NE|NW|SE|SW|North|South|East|West)"


def _drop_street_dir(q: str) -> str:
    """'4847 N Meade St, Denver' -> '4847 Meade St, Denver'.

    OSM frequently files a street with no directional prefix even where the
    postal address carries one, and Nominatim then matches nothing at all
    rather than falling back. Only ever tried after the address as written.

    Ceiling: in a city where the direction distinguishes two real streets
    (Manhattan's W 4th vs E 4th) this can land on the wrong one. That only
    happens when the exact address already returned nothing, so the choice is
    an approximate pin against no pin at all.
    """
    # The lookahead is what stops this eating a street whose NAME is the
    # direction. "123 North St" and "500 East Ave, Rochester" are not numbered
    # addresses carrying a prefix — North and East ARE the streets, and the old
    # pattern turned them into "123 St" and "500 Ave", which name nothing
    # anywhere. Two more tokens before the comma keeps the real prefix case (a
    # name plus a suffix follows the direction) and drops the destructive one
    # (only a suffix does).
    return re.sub(rf"^(\d+\s+){_DIR}\.?\s+(?=[^,\s]+\s+[^,\s])", r"\1", q, flags=re.I)


# Deliberately short. "Fl"/"Floor" are absent because ", FL 32801" is a Florida
# address, not a floor number, and stripping it would delete the state and zip.
_UNIT = r"(?:Bldg|Building|Ste|Suite|Unit|Apt|Apartment|#)"


def _drop_unit(q: str) -> str:
    """'3455 Ringsby Ct, Unit 105A, Denver, CO' -> '3455 Ringsby Ct, Denver, CO'.

    Nominatim geocodes buildings, not the offices inside them, and returns nothing
    at all for an address carrying a suite. Four Denver restaurants were pinned on
    the city centroid because of it — a food-hall counter, two units and a
    building number, each of which resolves exactly once the segment is dropped.

    Only ever tried after the address as written, so a Nominatim that does know
    the unit still wins.
    """
    # `[^,]*`, not `[\w-]+`: a unit segment runs to the next comma, and taking
    # only its first token left the rest of it welded to the street. "123 Main
    # St, Apt 4 B" came out as "123 Main St B" and "345 Main St, Unit 5 Building
    # A, Denver" as "345 Main St Building A, Denver" — queries for addresses that
    # do not exist, which is the failure this function exists to remove.
    return re.sub(rf",\s*{_UNIT}\.?\s*[^,]*", "", q, flags=re.I)


def _extract_city_state(loc: str) -> str:
    """Pull 'City, ST' or 'City, ST ZIP' tail off a free-form address."""
    if not loc:
        return ""
    # ZIP+4 and a lower-cased state both still name a state. Demanding [A-Z]{2}
    # and a bare five-digit ZIP made "Denver, Co 80202" and "Denver, CO 80202-1234"
    # return nothing at all, which switches the name fallback off for the whole
    # address rather than making it less precise.
    m = re.search(r",\s*([A-Za-z][A-Za-z .'-]+,\s*[A-Za-z]{2}(?:\s+\d{5}(?:-\d{4})?)?)\s*$", loc)
    return m.group(1).strip() if m else ""


def _extract_state(loc: str) -> str:
    """Pull just the 'ST' off a free-form address.

    A place inside a national park is not inside the nearest town's boundary, so
    'Bear Lake Trailhead, Estes Park, CO' finds nothing while 'Bear Lake
    Trailhead, CO' lands on it. The state still rules out the identically-named
    trailhead in Alaska, which a bare name search would return instead.
    """
    m = re.search(r",\s*([A-Za-z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$", loc or "")
    return m.group(1).upper() if m else ""


def _throttle() -> None:
    """Hold the shared 1.1 s Nominatim floor. Every request in this module waits here."""
    global _last_call
    with _lock:
        delta = time.monotonic() - _last_call
        if delta < MIN_INTERVAL_SEC:
            time.sleep(MIN_INTERVAL_SEC - delta)
        _last_call = time.monotonic()


def lookup_area(query: str) -> dict | None:
    """Resolve a place name to coordinates plus its administrative hierarchy.

    geocode() answers "where is this" with a coordinate pair and throws the rest
    away. This answers "what is this" as well: which neighborhood, which borough,
    which city, which country. The /food skill needs the hierarchy because every
    place row carries denormalized city/borough/neighborhood columns and the map
    rolls up on them, so a coordinate alone is not enough to file a result.

    Returns None when Nominatim has no answer, so a failed resolve is visible to
    the caller rather than filed as an empty string.
    """
    _throttle()
    params = {"q": query, "format": "json", "limit": 1, "addressdetails": 1}
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            return None
        hit = data[0]
        addr = hit.get("address", {})
        # Nominatim's borough-level key varies by city. In NYC the borough arrives
        # as "suburb" and the city as "city"; elsewhere "city_district" carries it.
        return {
            "lat": float(hit["lat"]),
            "lng": float(hit["lon"]),
            "neighborhood": addr.get("neighbourhood") or addr.get("quarter") or "",
            "borough": addr.get("suburb") or addr.get("city_district") or "",
            "city": (addr.get("city") or addr.get("town")
                     or addr.get("village") or addr.get("municipality") or ""),
            "state": addr.get("state", ""),
            "country": addr.get("country_code", "").upper(),
            "display_name": hit.get("display_name", ""),
        }
    except Exception as e:
        logger.warning("area lookup failed for %r: %s", query, e)
        return None


def _lookup(query: str) -> tuple[float, float] | None:
    _throttle()
    params = {"q": query, "format": "json", "limit": 1, "addressdetails": 1}
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            return None
        hit = data[0]
        # A house-numbered query that comes back as the whole street is a miss, not
        # a hit: Nominatim answers "1136 Broadway, Denver" with the centroid of
        # Broadway itself, three miles from the building. Accepting that silently
        # pinned two nightclubs on the same wrong corner and stopped the name
        # fallback below from ever running. Treat it as no result so the caller
        # keeps trying.
        # `\S`, not `[A-Za-z]`: on an ordinal street the token after the house
        # number is itself a digit ("17411 81st Ave"), and requiring a letter made
        # this whole guard stop applying there. That is how a Commerce City rental
        # counter got written as the centroid of East 81st Avenue, 6.6 mi west of
        # the lot — inside any sane distance gate, and wrong.
        if re.search(r"(?:^|,\s*)\d+\s+\S", query) and not hit.get("address", {}).get("house_number"):
            logger.info("street-centroid result rejected for %r (%s)", query, hit.get("display_name", ""))
            return None
        return float(hit["lat"]), float(hit["lon"])
    except Exception as e:
        logger.warning("lookup failed for %r: %s", query, e)
        return None


def _address_candidates(query: str) -> list[str]:
    """Address-as-written, then progressively cleaned, most specific first."""
    cleaned = _clean(query)
    stripped = _drop_unit(cleaned)
    return [query, cleaned, stripped, _drop_street_dir(stripped)]


def _name_candidates(query: str, name: str, country: str | None = None) -> list[str]:
    """Fallback: the place by name, for landmarks Nominatim knows but whose
    street address it doesn't. The name gets the same cleaning the address did
    — a raw "Bear Lake Trailhead -> Lake Haiyaha" matches nothing.

    A bare name is never tried. It is the one query with nothing to
    disambiguate it, so it does not fail — it returns the wrong planet-half
    confidently: "ACE" (a rental counter in Aurora) landed in central France,
    and other counters in Panama, Germany and south Texas.

    This guard used to be inverted: it returned None when a state existed and
    fell THROUGH to the bare query when the address had no state at all. That
    is backwards — no state is the case with the least to constrain the
    search, not the most. An address the earlier queries could not place gets
    no pin; a null renders as "not on the map yet", a wrong one renders as an
    answer and feeds distances and drive times downstream.
    """
    named = _clean(name)
    out = []
    city = _extract_city_state(query)
    if city:
        out.append(f"{named}, {city}")
    state = _extract_state(query)
    if state:
        out.append(f"{named}, {state}")
    if out:
        return out
    # Abroad there is no 'City, ST' tail, which used to switch this whole rescue
    # off for trip 60 (El Salvador). The address's own last two segments are the
    # locality ("La Libertad, El Salvador"), and the trip's country is the
    # backstop for an address that never names one.
    # ponytail: text scoping, not Nominatim countrycodes; that needs a
    # name -> ISO table, add it if a name ever matches across a border.
    segs = [s.strip() for s in _clean(query).split(",") if s.strip()]
    if len(segs) >= 2:
        out.append(f"{named}, {', '.join(segs[-2:])}")
    if country and country.lower() not in query.lower():
        out.append(f"{named}, {country}")
    return out


def geocode(query: str, name: str | None = None,
            country: str | None = None) -> tuple[float, float] | None:
    """`country` is the trip's own (last segment of trips.destination); it only
    scopes the by-name fallback for addresses with no US state tail."""
    if not query or not query.strip():
        return None
    tried = set()

    def try_query(q):
        if not q or q in tried:
            return None
        tried.add(q)
        return _lookup(q)

    for q in _address_candidates(query):
        coords = try_query(q)
        if coords:
            return coords
    if name:
        for q in _name_candidates(query, name, country):
            coords = try_query(q)
            if coords:
                return coords
    return None


def miles_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle miles between two (lat, lng) pairs.

    Lives here because the only callers are geocode sanity checks — a result
    hundreds of miles from where the thing is supposed to be is a wrong answer,
    not a near miss.
    """
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(min(1.0, math.sqrt(h)))


def reverse_geocode(lat: float, lon: float) -> str:
    """Convert GPS coordinates to a short readable address.

    Returns 'house_number road, city, state' or '' on failure.
    Respects the same 1.1 s rate limit as forward geocoding.
    """
    _throttle()
    params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1}
    url = f"{NOMINATIM_REVERSE_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        addr = data.get("address", {})
        parts: list[str] = []
        num = addr.get("house_number", "")
        road = addr.get("road", "")
        if num and road:
            parts.append(f"{num} {road}")
        elif road:
            parts.append(road)
        city = addr.get("city") or addr.get("town") or addr.get("village") or ""
        state = addr.get("state", "")
        if city:
            parts.append(city)
        if state:
            parts.append(state)
        return ", ".join(parts) if parts else data.get("display_name", "")
    except Exception as e:
        logger.warning("reverse lookup failed for (%s, %s): %s", lat, lon, e)
        return ""


def format_address(addr: dict, fallback: str = "") -> str:
    """One Nominatim `address` block as a single postal line.

    The point is a SHAPE, not a lookup: every address written through this
    function comes out as `<street>, <city>, <region> <postcode>[, <country>]`,
    so a set of them sorts, dedupes and reads as one column instead of as
    however each person happened to type theirs.

    The region is the ISO subdivision code where Nominatim carries one
    ("US-CO" → "CO"), because "Colorado" and "CO" are the same state written
    two ways and picking one is the entire job here. Country is dropped for the
    US — a domestic address that names its country reads as an export form —
    and kept everywhere else, since that is the half that disambiguates.

    Falls back to `fallback` (the caller's display_name) when the block has no
    street and no city, which is what a whole-country or ocean result looks
    like.
    """
    num, road = addr.get("house_number", ""), addr.get("road", "")
    street = f"{num} {road}".strip() if road else ""
    city = (addr.get("city") or addr.get("town") or addr.get("village")
            or addr.get("municipality") or addr.get("suburb") or "")
    iso = addr.get("ISO3166-2-lvl4", "")
    region = iso.split("-", 1)[1] if "-" in iso else addr.get("state", "")
    tail = " ".join(p for p in (region, addr.get("postcode", "")) if p)
    country = addr.get("country", "")
    cc = addr.get("country_code", "").upper()
    parts = [p for p in (street, city, tail) if p]
    if not parts:
        return fallback
    if cc and cc != "US" and country:
        parts.append(country)
    return ", ".join(parts)


# ── Address autofill (NYC Geosearch first, Photon only outside the city) ─────
#
# Everyone who fills this field lives in one metro, and they all type the house
# number FIRST. That is the whole requirement, and it is what disqualified two
# world geocoders in a row.
#
# Photon cannot answer a number-led query at all. It fuzzy-matches the query as
# free text, so a leading number is scored against place NAMES: '428' returned
# "M.S. 428 - Global Innovators Academy" (house number 4012) and '428 he'
# returned "426 Clinton Deli & Grocery". Asked for fifty results inside the NYC
# box, '428' came back with twenty-eight rows and ZERO whose house number even
# began with 428. There is no tuning past that — the index cannot do it.
#
# NYC Geosearch is Pelias over the city's own address list (PAD), built for this
# exact box. It prefix-matches the number and the street together:
#
#   '428'      428 BR 4 WALK / 428 49 AVENUE / 42804 WOODHAVEN BOULEVARD
#   '428 h'    428 HICKS ST / 428 HEGEMAN AVE / 428 HANCOCK ST / 428 HART ST
#   '428 he'   428 HEGEMAN AVE / 100 EXAMPLE ST / 428 HERNANDEZ PL
#   '428 hen'  100 EXAMPLE STREET
#
# It is NYC-only and answers nothing outside the five boroughs, which is what
# the second pass is for. Photon keeps that job: out-of-town addresses are rare
# here, arrive fully typed, and are the case Photon is actually good at.
#
# ── Photon (the widen pass only) ─────────────────────────────────────────────
#
# The account page's address field is a TYPEAHEAD, and Nominatim is a geocoder.
# That mismatch is not tunable. Traced letter by letter over four real NYC
# addresses, Nominatim answers a half-typed word by abandoning the local match
# entirely, so the right answer appears and then vanishes as you keep typing:
#
#   '350 5th Ave'      350 5th Avenue, New York, NY 10118     <- right
#   '350 5th Ave Ne'   Central-Mid-Levels Escalator, Hong Kong
#   '1 Wall St'        1 Wall Street, New York, NY 10005      <- right
#   '1 Wall S'         1 Wall, Wuppertal, Deutschland
#   '1 Wall St Ne'     1 Wall Street, Stromsburg, Nebraska
#   '200 Eastern P'    200 Eastern Corner Road, Campton, NH
#
# Photon is OSM's autocomplete front end (same data, built for prefixes). Over
# the identical traces it produced ZERO out-of-area results, locked onto the
# right answer sooner ('350 5' at five characters, where Nominatim needed nine),
# and held it through every later keystroke instead of flickering.
#
# Nominatim keeps everything else in this module. It is good at what the rest of
# the file asks — a complete address in, one pin out — and that path is proven.
PHOTON_URL = "https://photon.komoot.io/api/"
# Still sent as a proximity hint even with no box, so an out-of-town query that
# is ambiguous leans toward the side of the country everyone here starts from.
NYC_LAT, NYC_LON = 40.7128, -74.0060
# Widening past the city needs the query to be saying something. Across ~90
# traced keystrokes exactly one local prefix came back empty from home
# ('350 5t', six characters), so anything shorter than this is a half-typed word
# rather than an address somewhere else — and widening on it is precisely how
# the old fallback let Hong Kong and Wuppertal into the list.
_WIDEN_MIN = 10
_photon_last = 0.0

# Photon fuzzy-matches the WHOLE query as text, so a leading house number is just
# another token — it will happily answer '428 he' with "426 Clinton Deli &
# Grocery" (matched on the name) or "M.S. 428 - Global Innovators Academy"
# (matched on the school's number). Traced on 100 Example Street: not one row in
# the first four keystroke-prefixes actually had house number 428, and the right
# answer only surfaced at '428 henr' — carried entirely by the street name.
# So when the query opens with a number, that number is a HARD filter, not a
# hint. Nothing beats nothing here: an empty list leaves the last suggestions up
# (see the client's close()), whereas a wrong-numbered row invites a wrong pick.
_QUERY_HOUSENUM = re.compile(r"^\s*(\d+[a-zA-Z]?)\b")


def _housenum(q: str) -> str:
    """The house number a query opens with, lowercased, or '' if it opens with a word."""
    m = _QUERY_HOUSENUM.match(q or "")
    return m.group(1).lower() if m else ""

# Photon returns the state spelled out where the postal shape wants the code, and
# "New York, New York 10118" is the drift this whole feature exists to stop.
_US_STATE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


def _photon_line(props: dict) -> tuple[str, bool]:
    """One Photon feature as a postal line, plus whether it names a street.

    Same shape format_address emits for Nominatim, so a row picked here is
    indistinguishable from one geocoded anywhere else in the vault.
    """
    street = props.get("street") or ""
    num = props.get("housenumber") or ""
    # `name` carries the POI ("Empire State Building") when there is no street;
    # it is the only thing that makes such a row identifiable.
    line1 = " ".join(x for x in (num, street) if x) or (props.get("name") or "")
    city = props.get("city") or props.get("county") or ""
    cc = (props.get("countrycode") or "").upper()
    state = props.get("state") or ""
    if cc == "US":
        state = _US_STATE.get(state.lower(), state)
    tail = " ".join(x for x in (state, props.get("postcode") or "") if x)
    parts = [x for x in (line1, city, tail) if x]
    if cc and cc != "US" and props.get("country"):
        parts.append(props["country"])
    return ", ".join(parts), bool(street)


def _photon_once(q: str, limit: int) -> list[dict]:
    """One unbounded Photon pass, formatted and deduped. [] on any failure."""
    global _photon_last
    # Photon publishes no hard floor the way Nominatim does, but it is somebody
    # else's free service. The client already debounces at 450ms; this is the
    # backstop for anything that calls in a loop.
    delta = time.monotonic() - _photon_last
    if delta < 0.35:
        time.sleep(0.35 - delta)
    _photon_last = time.monotonic()
    params = {"q": q, "limit": max(1, min(limit * 2, 20)), "lang": "en",
              "lat": NYC_LAT, "lon": NYC_LON}
    url = f"{PHOTON_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("wide address search failed for %r: %s", q, e)
        return []
    out: list[dict] = []
    seen: set[str] = set()
    # Prefix, not equality: someone typing 428 is still typing, and 4281 is a
    # live candidate until they stop. Equality also throws away the ranges OSM
    # carries ("420-442"), which a typed 428 sits inside.
    want_num = _housenum(q)
    for f in data.get("features", []):
        props = f.get("properties") or {}
        if want_num and not (props.get("housenumber") or "").lower().startswith(want_num):
            continue
        line, has_street = _photon_line(props)
        if not line or line in seen:
            continue
        seen.add(line)
        lon, lat = (f.get("geometry") or {}).get("coordinates", [None, None])[:2]
        out.append({"address": line, "street": has_street,
                    "lat": lat, "lng": lon})
    # A row with no street is a neighbourhood or a park, not an address. Dropped
    # only when something with a street survives, so a deliberate search for a
    # place still answers.
    with_street = [h for h in out if h["street"]]
    return [{k: v for k, v in h.items() if k != "street"}
            for h in (with_street or out)][:limit]


GEOSEARCH_URL = "https://geosearch.planninglabs.nyc/v2/autocomplete"
_geosearch_last = 0.0


def _titlecase(text: str) -> str:
    """The city's ALL CAPS as a name. Both repairs are for real NYC streets.

    ponytail: str.title() plus two fixes, not a name-particle library. It gets
    "Saint Mark's Place" and "McDonald Way" right, which are the two shapes that
    actually appear; anything else that shows up wrong gets its own line here.
    """
    out = text.title()
    out = re.sub(r"(?<=\w)'S\b", "'s", out)
    return re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), out)


def _geosearch_line(props: dict) -> str:
    """One Geosearch feature as the same postal line format_address emits.

    The city comes off `label` rather than any single field, because the right
    answer differs per borough and Pelias already worked it out: 11231 is
    "Brooklyn", 10118 is "New York" (not "Manhattan"), and a Queens ZIP is
    "Long Island City" or "Middle Village" rather than "Queens". label is
    "<name>, <city>, <state>, <country>", so the city is third from the end.
    """
    num = props.get("housenumber") or ""
    street = props.get("street") or ""
    line1 = _titlecase(" ".join(x for x in (num, street) if x) or props.get("name") or "")
    parts = [x.strip() for x in (props.get("label") or "").split(",")]
    city = parts[-3] if len(parts) >= 3 else ""
    tail = " ".join(x for x in (props.get("region_a") or "",
                                props.get("postalcode") or "") if x)
    return ", ".join(x for x in (line1, city, tail) if x)


def _geosearch_once(q: str, limit: int) -> list[dict]:
    """One NYC Geosearch pass, formatted and deduped. [] on any failure."""
    global _geosearch_last
    delta = time.monotonic() - _geosearch_last
    if delta < 0.35:
        time.sleep(0.35 - delta)
    _geosearch_last = time.monotonic()
    url = f"{GEOSEARCH_URL}?{urllib.parse.urlencode({'text': q, 'size': max(1, min(limit * 2, 20))})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("nyc address search failed for %r: %s", q, e)
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for f in data.get("features", []):
        line = _geosearch_line(f.get("properties") or {})
        if not line or line in seen:
            continue
        seen.add(line)
        lon, lat = (f.get("geometry") or {}).get("coordinates", [None, None])[:2]
        out.append({"address": line, "lat": lat, "lng": lon})
        if len(out) >= limit:
            break
    return out


def search_addresses(query: str, limit: int = 6,
                     nyc_first: bool = True) -> list[dict]:
    """Address candidates for a partial query, each already postal-formatted.

    Backs the account page's address field. Home first, then the world: pass one
    is NYC Geosearch, which is the only one of the three engines tried that can
    answer a query led by a house number. Pass two is Photon with no bounding
    box, and runs only when NYC had nothing AND the query is long enough to be
    an address somewhere else rather than a word in progress (see _WIDEN_MIN).
    Both the split and that gate are there for failures traced letter by letter
    — see the block comment above.

    Returns `[{address, lat, lng}]`, deduped on the formatted string.
    """
    q = (query or "").strip()
    if len(q) < 3:
        return []
    if nyc_first:
        near = _geosearch_once(q, limit)
        if near or len(q) < _WIDEN_MIN:
            return near
    return _photon_once(q, limit)


# ── Timezone from coordinates ────────────────────────────────────────────────
# Nominatim does not carry a zone, so this is a second host. Keyless, and called
# once per airport ever — the answer caches in `airports.tz` and an airport does
# not move between zones — so it deliberately does not share `_throttle()` with
# the Nominatim calls above.
TIMEAPI_URL = "https://timeapi.io/api/timezone/coordinate"

# An IANA name, loosely: "America/Denver", "Europe/London", "UTC". Checked
# because the value is fed straight to Intl.DateTimeFormat in the browser and to
# zoneinfo on this side, and a 200 carrying an error body would poison the cache.
_IANA = re.compile(r"^[A-Za-z][A-Za-z0-9+_-]*(?:/[A-Za-z0-9+._-]+){0,2}$")


def timezone_at(lat: float | None, lng: float | None) -> str | None:
    """IANA zone name for a coordinate, or None if the lookup fails.

    None means "ask again later", never "no zone" — the caller must not write it
    over a zone already cached. `upsert_airport` enforces that with an empty
    string; this returns None so the two cases stay distinguishable.
    """
    if lat is None or lng is None:
        return None
    url = f"{TIMEAPI_URL}?{urllib.parse.urlencode({'latitude': lat, 'longitude': lng})}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            tz = (json.loads(resp.read().decode("utf-8")) or {}).get("timeZone") or ""
    except Exception as e:
        logger.warning("timezone lookup failed for %s,%s: %s", lat, lng, e)
        return None
    tz = str(tz).strip()
    if not _IANA.match(tz):
        logger.warning("timezone lookup returned an unusable zone for %s,%s: %r", lat, lng, tz)
        return None
    return tz


def demo() -> None:
    """Self-check for the zone lookup's parsing and its guards. Network is only
    touched for the one real coordinate; everything else is offline."""
    assert timezone_at(None, None) is None
    assert _IANA.match("America/Denver")
    assert _IANA.match("America/Argentina/Buenos_Aires")
    assert _IANA.match("UTC")
    assert not _IANA.match("")
    assert not _IANA.match("not a zone")          # the space is the tell
    assert not _IANA.match("<html>error</html>")
    print("timezone_at guards ok;  DEN ->", timezone_at(39.8607, -104.6854))


if __name__ == "__main__":
    demo()
