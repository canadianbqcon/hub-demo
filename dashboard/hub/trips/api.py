"""Trips Hub blueprint — routes under /trips.

Ported from the legacy 5001 dashboard. Differences:
- No AI trip-research endpoint (needed an Anthropic key that isn't available).
- Interest matching is keyword/token-based (no model call) — see `_keyword_match`.
- Google Calendar push is kept (gcal), reached via the dashboard/ path the Hub
  already puts on sys.path.
"""

from __future__ import annotations

import contextlib
import logging
import datetime
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from flask import (
    Blueprint, current_app, jsonify, make_response, redirect, render_template,
    session, url_for,
)

from checklists import db as checklists_db  # noqa: F401 - facade owns it (Rule 1); grocery/packing sections import it themselves

from . import db
from . import forms_intake  # noqa: F401 - facade owns it (Rule 1); prefs/account sections import it themselves
from . import preferences as prefs  # noqa: F401 - facade owns it (Rule 1); prefs/account sections import it themselves

bp = Blueprint(
    "trips",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/trips",
)

# dashboard/ on sys.path → vault_path, gcal, geocode (the Hub already inserts it,
# but make the blueprint importable standalone too).
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

logger = logging.getLogger(__name__)

_VAULT_ROOT = vault_root()

# gcal / geocode are optional — guard the import so the module still loads if the
# Google libs or geocode deps are missing on a given machine.
# Split on TYPE_CHECKING so the checker sees the real modules while the runtime
# keeps the optional fallback. Every gcal call below is gated on _cal_ready() (which
# tests `gcal and ...`), but that guard lives in another function and a type checker
# can't follow it, so a plain `gcal = None` fallback makes all ~7 guarded uses read
# as errors on None. Behaviour at runtime is unchanged.
if TYPE_CHECKING:
    import gcal
    import geocode as geocode_mod
    import nearby as nearby_mod
else:
    try:
        import gcal  # noqa: E402
    except Exception:  # pragma: no cover
        gcal = None

    try:
        import geocode as geocode_mod  # noqa: E402
    except Exception:  # pragma: no cover
        geocode_mod = None

    try:
        import nearby as nearby_mod  # noqa: E402
    except Exception:  # pragma: no cover
        nearby_mod = None


def _cal_ready() -> bool:
    return bool(gcal and gcal.is_authenticated() and not gcal.needs_reauth())


# ── Calendar reconcile (gcal deletions → trips.db) ──────────────────────────────
# The trip↔calendar sync is one-directional (DB pushes to Calendar). If a trip's
# event is deleted straight in Google Calendar, the DB never finds out. This
# daily-gated, future-only pass closes that gap by SOFT-flagging the row
# (cal_status='deleted') so the UI can surface it — it never hard-deletes a trip.

_RECONCILE_STAMP = Path(__file__).resolve().parents[2] / ".trip-cal-reconcile-stamp"


def _reconcile_deleted_trips() -> None:
    """Once per calendar day, check each future trip's calendar event and flag any
    that have been deleted/cancelled outside the dashboard. Best-effort: any
    failure (no auth, missing column, API error) is swallowed so a trips page load
    never breaks on it."""
    if not _cal_ready():
        return
    today = datetime.date.today().isoformat()
    # unreadable stamp → suppress and fall through to reconcile
    with contextlib.suppress(Exception):
        if _RECONCILE_STAMP.exists() and _RECONCILE_STAMP.read_text().strip() == today:
            return
    try:
        for trip in db.list_trips():
            eid = trip.get("cal_event_id")
            end = trip.get("end_date") or ""
            # future/ongoing only — a trip that already ended doesn't matter
            if not eid or end < today:
                continue
            gone = gcal.event_is_gone(eid)
            if gone is None:
                continue  # uncertain read — leave the row untouched
            cur = trip.get("cal_status") or ""
            if gone and cur != "deleted":
                db.set_trip_cal_status(trip["id"], "deleted")
            elif not gone and cur == "deleted":
                db.set_trip_cal_status(trip["id"], "")  # event came back — clear flag
        _RECONCILE_STAMP.write_text(today)
    except Exception:  # noqa: BLE001
        logger.exception("trip reconcile failed")


# ── Page ──────────────────────────────────────────────────────────────────────


def _no_store(resp):
    # never let the browser serve a stale HTML document — the page references
    # versioned css/js, but the document itself must always re-fetch so layout
    # changes land on a plain reload (no hard-refresh needed).
    resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    return resp


# ── Preview ("view as") ───────────────────────────────────────────────────────
#
# Sam looking at a member's board from Hub, for a moment, without becoming
# them anywhere. It is three values and nothing else, because being a guest was
# only ever three values: the guest body class, which trips are listed, and whose
# flights sort first. The board itself is the same board.
#
# It lives on Hub deliberately. Hub is the private, password-gated port and
# already knows who is asking, so a preview needs no credential of its own — the
# public mirror had to be handed a member's passcode precisely because it knows
# nobody. Nothing here touches the mirror, the keypad, or the member's row, so a
# preview leaves last_seen exactly where it was: it is not a sign-in.
#
# The route is withheld from the mirror (public_app._WITHHELD_PREFIXES). Mounted
# there it would let any unlocked guest re-scope themselves onto someone else's
# trips with a GET, which is the one thing the gate exists to prevent.
# Sam's own contact slug. The one member key that is not looked up, because
# Hub IS him: an unpinned request naming nobody is his own account. Same literal
# as trips.js / trips-cost.js ME_SLUG and finances.trip_debts.ME_SLUG.
ME_SLUG = "sam-rivera"

_PREVIEW_KEY = "preview_slug"
_PREVIEW_NAME = "preview_name"


def _preview_slug() -> str:
    """The member key being previewed, or "" — the whole state of the feature."""
    return session.get(_PREVIEW_KEY) or ""


def _preview_name() -> str:
    """What to call them on screen. The key is a slug and for un-noded crew it is
    "name:nina ford", which is a database detail and not a person's name."""
    return session.get(_PREVIEW_NAME) or ""


def _guest_mode() -> bool:
    """Render as a guest sees it: set process-wide by the mirror, per-session here."""
    return bool(current_app.config.get("GUEST", False) or _preview_slug())


@bp.route("/preview/<int:code_id>")
def preview_on(code_id: int):
    """Start previewing as the member holding this guest code.

    Keyed on the guest_codes row rather than a slug typed into the URL so that
    the only previewable people are the ones who actually have access — a
    preview then cannot show a view no real member could ever have.
    """
    if current_app.config.get("GUEST", False):
        return jsonify({"error": "not found"}), 404   # belt: the mirror withholds this
    row = db.guest_code_by_id(code_id)
    if not row or row.get("status") != "approved" or not row.get("contact_slug"):
        return jsonify({"error": "no approved member for that code"}), 404
    session[_PREVIEW_KEY] = row["contact_slug"]
    session[_PREVIEW_NAME] = row.get("name") or row["contact_slug"]
    return redirect(url_for("trips.index"))


@bp.route("/preview/off")
def preview_off():
    session.pop(_PREVIEW_KEY, None)
    session.pop(_PREVIEW_NAME, None)
    return redirect(url_for("trips.index"))


def _crew_waiting() -> int:
    """Code requests plus trip submissions: everything the crew page has waiting on Sam."""
    from . import intake
    with db._conn() as conn:
        return db.pending_guest_code_count() + len(intake.list_pending(conn))


@bp.route("/crew")
def crew():
    """Who holds a code, who is asking for one, and what guests sent in. The ◉ top-bar
    panel this replaces rode on every page; it is one page under trips now. The mirror
    withholds the prefix too (public_app._WITHHELD_PREFIXES); this 404 is the belt."""
    if current_app.config.get("GUEST", False):
        return jsonify({"error": "not found"}), 404
    return _no_store(make_response(render_template("crew.html")))


@bp.route("/")
def index():
    # Landing: the countdown spine of every trip. This used to be the planner
    # itself; the planner now lives at /trips/<id> and the top-bar <select> that
    # used to switch trips is gone.
    _reconcile_deleted_trips()
    return _no_store(make_response(render_template(
        "trips-landing.html", guest=_guest_mode(), preview=_preview_name(),
        # what the crew link's badge counts; Hub only, the mirror never renders the link
        waiting=0 if _guest_mode() else _crew_waiting(),
        # Same reader key the planner gets. The landing card runs the same cost
        # model, so without it every "your share" on this page was Sam's
        # share no matter whose link was open.
        viewer=_bound_key(),
    )))


# ── The hallmark page ──────────────────────────────────────────────────────
# One tab per trip whose content is the reason the trip exists. Its module lives
# in frontend/hallmark/, NOT in frontend/static/ — the blueprint hands its whole
# static folder out, so anything in there is fetchable by any guest who guesses
# the filename, and one of these pages is a surprise party being kept from a
# member of its own crew. Served from here instead, behind the same reader key
# the rest of the board is bound to.
#
# `hidden` is a list of member keys (db.member_key: a contact slug, or
# "name:<lowercased name>"). A reader on that list gets a 404 and a template with
# no script tag: on their board the tab is not hidden, it was never built.
# Sam on Hub is pinned to nobody and always sees it.
_HALLMARK: dict[int, dict] = {
    59: {"slug": "lostlands", "hidden": []},                    # Columbus — Lost Lands
    60: {"slug": "wedding", "hidden": []},                      # El Salvador — Josh & Amanda
    61: {"slug": "denver-birthday", "hidden": ["owen-hale"]},   # Denver — Aaron's birthday
}

_HALLMARK_DIR = Path(__file__).resolve().parent / "frontend" / "hallmark"


def _hallmark_for(trip_id: int) -> dict | None:
    """The hallmark module this READER may have for this trip, or None.

    Returns None both for "no such page" and for "not for you", deliberately: the
    two are indistinguishable from the browser's side, which is the point.
    """
    cfg = _HALLMARK.get(trip_id)
    if not cfg:
        return None
    bound = _bound_key()
    if bound and bound in cfg["hidden"]:
        return None
    return cfg


@bp.route("/<int:trip_id>/hallmark.<any(js, css):ext>")
def hallmark_asset(trip_id: int, ext: str):
    cfg = _hallmark_for(trip_id)
    if not cfg:
        return jsonify({"error": "not found"}), 404
    path = _HALLMARK_DIR / f"{cfg['slug']}.{ext}"
    if not path.is_file():
        return jsonify({"error": "not found"}), 404
    resp = make_response(path.read_text(encoding="utf-8"))
    resp.headers["Content-Type"] = (
        "text/css; charset=utf-8" if ext == "css" else "application/javascript; charset=utf-8"
    )
    # Same no-store the board itself gets: whether this file exists at all depends
    # on who is asking, and a shared cache that answered for the last reader would
    # hand it to the one person it is kept from.
    return _no_store(resp)


@bp.route("/<int:trip_id>")
def planner(trip_id: int):
    # The planner, scoped to one trip. The id is injected into the document so
    # trips.js boots straight into it — no localStorage, no extra round-trip.
    if not db.get_trip(trip_id):
        return redirect(url_for("trips.index"))
    return _no_store(make_response(render_template(
        "trips.html",
        trip_id=trip_id,
        exposed=current_app.config.get("EXPOSED", False),
        # Set only by the public mirror (trips/public_app.py). Hub never sets it,
        # so Hub renders exactly as before.
        guest=_guest_mode(),
        preview=_preview_name(),
        # Who is reading this page, as the same member key guest codes are linked
        # on (db.member_key: a contact slug, or "name:<lowercased name>"). The
        # board puts that person's own flights first. Installed as a callable by
        # the public mirror, because the answer is per-request; Hub never sets it
        # and the board falls back to owner-first exactly as before.
        viewer=_bound_key(),
        # The hallmark module's slug, or "" — which is how the tag is withheld from
        # a reader the page is kept from, rather than served and then hidden.
        # Doubles as the cache-buster, so two trips never share a cached module.
        hallmark=(_hallmark_for(trip_id) or {}).get("slug", ""),
    )))


# Labels whose VALUE is an account or document number rather than a fact about
# the trip: an airline loyalty account, a 13-digit e-ticket, a membership id.
# They sit on the row because Sam needs them at a counter, and a guest
# reading the shared itinerary never does. The reason to strip them is that they
# outlive the trip in a way the passcode gate cannot reach — revoking a code
# stops the next page load, it does not un-read a loyalty number somebody wrote
# down three months ago.
#
# Matched at the START of a line, so the whole "Rapid Rewards: 23086724091" line
# goes and "Fare: Basic" beside it stays.
_SECRET_LABELS = re.compile(
    r"^\s*(?:"
    r"e-?ticket|ticket(?:\s*(?:no|num|number|#))?"
    # "<brand> rewards" rather than the Southwest one by name: Ace, Hertz, Hilton
    # and the next one all spell it the same way, and the brand is the part that
    # changes. A bare "Rewards:" counts too.
    r"|(?:[a-z][a-z.'-]*\s+)?rewards|aeroplan(?:\s*member)?|mileage\s*?plus|skymiles|aadvantage"
    r"|true\s*blue|kris\s*flyer|flying\s*blue|miles\s*&?\s*more|executive\s*club"
    r"|frequent\s*flyer|ff\s*(?:no|num|number|#)|loyalty|member(?:ship)?(?:\s*(?:no|num|number|#|id))?"
    r"|known\s*travell?er(?:\s*number)?|ktn|redress|passport|visa\s*(?:no|num|number|#)"
    r")\b\s*[:#\-=]",
    re.I,
)

# The label list above is the common case. This is the backstop for a number
# nobody thought to label — eight digits is past any flight number, gate, seat,
# price or year the notes legitimately carry, and short of it we would be
# redacting "Model: A320".
_LONG_DIGITS = re.compile(r"\b\d{8,}\b")

# Free-text columns that reach a guest verbatim. `confirmation` is deliberately
# NOT here: a shared car or room is picked up with that code, so the crew needs
# it, and hiding it would break the thing the board is for.
_GUEST_TEXT_FIELDS = ("notes",)
_GUEST_TEXT_TABLES = ("flights", "housing", "transportation", "expenses", "activities")


# ── Fare search, packing ──────────────────────────────────────────────────────
# _FARE_KEEP / _FARE_TIMEOUT / _fare_note and _PACKING_* / packing_rank moved to
# api_items.py and api_packing.py (Task 4, to keep this facade under 500 lines)
# and are reached back here through the re-export at the bottom of this file.


# ── Members, guest codes, roster ──────────────────────────────────────────────
# Moved to api_access.py (Task 4); reached back here through re-export below.

# ── Crew preferences, forms, account page (api_prefs.py / api_account.py) ─────
# `_FREE_TEXT`, `CARD_VARIANTS`, `CARD_UNLOCKS`, `_SYNC_MIN_GAP` / `_last_sync`
# and `_OUTLIER_MIN_CREW` stay here (Rule 1); the moved functions reach them as
# `_api.<name>` — the sync throttle in particular is facade state
# api_prefs.sync_form_responses writes through as `_api._last_sync`.

# Free-text answers that mean "nothing to declare", stripped in
# api_prefs._denoise rather than on each surface (the rail once dropped
# Megan's "none" while the card printed it).
_FREE_TEXT = {
    "travel": ("absolute_nos", "physical_limits", "extra_notes"),
    "food": ("allergies", "wont_eat", "textures", "extra_notes"),
}

# A sync is two Google API round trips, so it is not something to run on every
# page load. This is the floor between them, shared by Hub and the public
# process — a guest hammering "I've filled it in" cannot turn the button into a
# request amplifier pointed at Google. Written through by api_prefs.sync_form_responses.
_SYNC_MIN_GAP = 20.0
_last_sync = 0.0

# The variants each slot offers, and the one source of truth for them: the
# picker renders this list, the POST validates against it, and trips.css names
# the same strings in its selectors. A seventh border is one entry here plus one
# CSS rule — which is the whole reason a saved look is three short strings.
CARD_VARIANTS = {
    "card_header": ["plain", "plate", "stamped", "rule", "knockout", "tape", "neon", "pill", "floating"],
    "card_shimmer": ["linear", "burst", "slick", "swirl", "grid", "wave", "dots", "scanlines"],
    "card_border": ["line", "brackets", "double", "sprocket", "foil", "ridge", "corners"],
}
# Which of the three things a member fills in unlocks which slot. The demo called
# the first one "basic details"; on this board that is a real wiki contact node,
# because a member who has only answered a form gets a synthesized contact whose
# path is empty (see the contact fallback in api_prefs.api_account).
CARD_UNLOCKS = {"card_header": "contact", "card_shimmer": "food", "card_border": "travel"}

# Below two people there is no group to be an outlier from, and "you are the only
# one who said that" about a crew of one is a sentence with no content.
_OUTLIER_MIN_CREW = 2

# ── Geocoding, nearby, interests, food, transit ───────────────────────────────
# Moved to api_places.py (Task 4). `_food_ready` stays here (Rule 1:
# test_trips_food_tab.py monkeypatches it directly on this module) and is
# written through by api_places._food_db as `_api._food_ready`.
_food_ready = False


# ── Sections (Task 3 of the trips-split plan) ───────────────────────────────
# Imported last, so bp and every module-level name above already exist by the
# time each section's `@bp.route` decorators run (Rule 3). Explicit re-exports,
# not `import *`, because that drops the underscore names tests and other
# sections hold onto (e.g. trips_api.prefs_state, trips_api._code_root).
from .api_trips import (  # noqa: E402,F401
    _hide_home_addresses, _redact_for_guest, _redact_notes, _scoped,
    api_create_trip, api_delete_trip, api_get_trip, api_list_trips,
    api_trips_summary, api_update_trip,
)
from .api_items import (  # noqa: E402,F401
    _add_fare_candidates, _as_item, _code_root, _fare_note, _fare_search_error,
    _seed_departures,
    api_add_activity, api_add_expense, api_add_flight, api_add_grocery,
    api_add_housing, api_add_transport, api_delete_activity, api_delete_expense,
    api_delete_flight, api_delete_grocery, api_delete_housing,
    api_delete_transport, api_search_fares, api_update_activity,
    api_update_expense, api_update_flight, api_update_grocery,
    api_update_housing, api_update_transport, api_upsert_opinion,
    _FARE_KEEP, _FARE_TIMEOUT,
)
from .api_packing import (  # noqa: E402,F401
    packing_rank,
    api_packing, api_packing_reset, api_packing_tick,
    _PACKING_CATEGORIES, _PACKING_OPTIONAL, _PACKING_ORDER,
)
# Task 4: access, prefs, account, places, discover, transit. Each also carries
# the plain stdlib names this file no longer imports directly (json, shutil,
# subprocess, os, urllib, time, ZoneInfo, request) — the manifest (Rule 4)
# still expects `trips.api.<name>` to resolve for every pre-split name.
from .api_access import (  # noqa: E402,F401
    api_add_member, api_clear_gate_freeze, api_delete_member, api_deny_guest_code,
    api_guest_codes, api_patch_guest_code, api_roster, api_share_url, api_update_member,
    json, request, shutil, subprocess,
)
from .api_prefs import (  # noqa: E402,F401
    _denoise, _form_keys, _live_prefs,
    api_claim_pref, api_pref_form, api_sync_prefs,
    api_trip_preferences, api_unmatched_prefs, form_links, preferences_page,
    sync_form_responses,
    time,
)
from .api_intake import (  # noqa: E402,F401
    api_approve_intake, api_intakes, api_reject_intake, api_submit_intake,
    _cross_site, _guard, intake_page, start_research,
)
from .api_account import (  # noqa: E402,F401
    _bound_key, _card_unlocked, _outlier_grid_tags, _outlier_row, _outliers, _submit_ref,
    api_account, api_address_search, api_my_prefs, api_pref_card, api_submit_prefs,
    prefs_state,
)
from .api_places import (  # noqa: E402,F401
    _address_of, _geo_anchor, _geocode_activity_rows, _geocode_airport_rows,
    _geocode_home_rows, _geocode_housing_rows, _geocode_transport_rows,
    _placed, _transport_where, _trip_country,
    api_geocode_trip, api_housing_nearby,
    GEO_MAX_MI,
)
from .api_discover import (  # noqa: E402,F401
    _activity_haystack, _food_db, _tokenize, _trip_area,
    api_analyze_interest, api_trip_food, api_trip_food_place,
    _STOPWORDS,
)
from .api_transit import (  # noqa: E402,F401
    _build_itineraries, _decode_polyline, _drops_token_hop, _leg_pt, _line_color,
    _local_min, _stop_name, _transit_leg, _transit_point, _transit_query,
    _transit_staleness, _feed_end, _ended_feeds,
    api_transit,
    _BUS_COLOR, _MOTIS_URL, _RIDE_TZ, _SUBWAY_COLORS, _TOKEN_HOP_MODES, _TOKEN_HOP_S,
    _TRANSIT_MODES,
    os, urllib, ZoneInfo,
)
