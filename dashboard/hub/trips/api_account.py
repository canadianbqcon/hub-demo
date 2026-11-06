"""The account page: card cosmetics, the outlier rail, and the two write
routes (form submit, "who am I").

Split from trips/api.py (Task 4 of the 2026-09-24 trips-split plan; split out
of the first draft of api_prefs.py, which came in over 500 lines by itself).
Reaches every trips.api global through the `_api` alias and every trips.db
function through `db`, both by attribute at call time (never
`from .api import ...` / `from .db import ...`), so a test's monkeypatch on
either facade still lands here. `_bound_key`, `_submit_ref` and
`prefs_state` live HERE and are reached from api_prefs.py (and every other
section) as `_api.<name>` — the same cross-section rule this file itself
uses to reach api_prefs.py's `_denoise` / `_live_prefs`. See
dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

import datetime

from flask import current_app, jsonify, request

from . import api as _api
from . import db
from . import forms_intake
from . import preferences as prefs


def _card_unlocked(ref: str) -> dict:
    """Which slots this person has earned, by the same rules the board renders."""
    done = db.prefs_for_refs([ref]).get(ref, {}) if ref else {}
    has_contact = bool(ref) and not ref.startswith(db.NAME_KEY) and bool(
        prefs.contact_for_member(_api._VAULT_ROOT, {"contact_slug": ref, "name": ""})
    )
    return {"card_header": has_contact,
            "card_shimmer": "food" in done,
            "card_border": "travel" in done}


@_api.bp.route("/api/prefs/card", methods=["GET", "POST"])
def api_pref_card():
    """Read or set the three cosmetic picks.

    Same identity rule as the form submit: on the mirror the ref comes off the
    unlocked guest_codes row, so a guest can only ever restyle their own card no
    matter what the body says. A pick into a slot the person has not unlocked is
    rejected rather than stored — storing it would mean the board renders one
    thing and the picker claims another.
    """
    unlocked = None
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        ref, _ = _submit_ref(body)
        if not ref:
            return jsonify({"error": "nobody is signed in"}), 403
        unlocked = _card_unlocked(ref)
        picks = {}
        for slot, allowed in _api.CARD_VARIANTS.items():
            if slot not in body:
                continue
            val = str(body.get(slot) or "").strip()
            if val and val not in allowed:
                return jsonify({"error": f"unknown {slot}: {val!r}"}), 400
            if val and not unlocked[slot]:
                return jsonify({"error": f"{slot} is not unlocked yet"}), 403
            picks[slot] = val
        look = db.set_card_look(ref, picks)
    else:
        ref, _ = _submit_ref(request.args)
        look = db.card_look(ref)
    return jsonify({"ref": ref, "card": look,
                    "unlocked": unlocked if unlocked is not None else _card_unlocked(ref),
                    "variants": _api.CARD_VARIANTS, "unlocks": _api.CARD_UNLOCKS})


@_api.bp.route("/api/prefs/address-search")
def api_address_search():
    """Address candidates for the account page's autofill.

    Exists so the five signup fields stop collecting five different spellings of
    the same street. Everyone typed their address free-hand, so the column held
    "St" and "Street", "NY" and "New York", some with a zip and some without —
    fine to read one at a time, useless the moment you want to sort them or
    check two people live in the same place. Picking from this writes the one
    postal shape geocode.format_address emits.

    A read with no subject: it takes a query string and returns public map data,
    so there is nothing here to scope to a member and nothing to leak. It is
    still gated by the session on the mirror, because an open geocoder proxy is
    someone else's rate budget being spent.

    Answers 200 with an empty list rather than an error when the geocoder is
    missing or the address service is down: the field is optional and typing it
    by hand stays the fallback, so a dead lookup should not put an error under an
    input that is working fine.
    """
    q = (request.args.get("q") or "").strip()
    if not _api.geocode_mod or len(q) < 3:
        return jsonify({"results": []})
    try:
        hits = _api.geocode_mod.search_addresses(q, limit=6)
    except Exception as e:  # noqa: BLE001 - the field degrades to free text
        _api.logger.warning("address search failed for %r: %s", q, e)
        return jsonify({"results": []})
    # `results` is the strings the account page's combobox renders; `places` is the
    # same hits with the coordinates still attached, which is what the day-of ride
    # card needs — an edited stop has to become a point before it can go in a Lyft
    # link, and geocoding it a second time would be a second round trip for an
    # answer this call already has. Additive: AddrCombo reads `results` and is
    # untouched.
    return jsonify({
        "results": [h["address"] for h in hits],
        "places": [{"address": h["address"], "lat": h["lat"], "lng": h["lng"]} for h in hits],
    })


def _outlier_grid_tags(contacts: list[dict], prefs_key: str, grid_key: str) -> list[str]:
    """Every tag anyone in the crew has rated on this grid, first-seen order."""
    tags: list[str] = []
    for c in contacts:
        for tag in ((c.get(prefs_key) or {}).get(grid_key) or {}):
            if tag not in tags:
                tags.append(tag)
    return tags


def _outlier_row(ref: str, me: dict, contacts: list[dict], prefs_key: str,
                  grid_key: str, tag: str, rank: dict) -> dict | None:
    """This tag's outlier row for `ref`, or None when nobody stands alone on it."""
    mine = ((me.get(prefs_key) or {}).get(grid_key) or {}).get(tag)
    if mine not in rank:
        return None
    others = []
    for c in contacts:
        if c.get("slug") == ref:
            continue
        r = ((c.get(prefs_key) or {}).get(grid_key) or {}).get(tag)
        if r in rank:
            others.append((c.get("name") or "", r))
    if not others:
        return None
    mine_r = rank[mine]
    ranks = [rank[r] for _, r in others]
    if mine_r > max(ranks):
        side = "keener"
    elif mine_r < min(ranks):
        side = "cooler"
    else:
        return None
    return {
        "grid": grid_key, "tag": tag, "yours": mine, "side": side,
        # The nearest other person, so the row can say who you are pulling
        # against rather than only that you are. Ties keep roster order.
        "nearest": sorted(others, key=lambda x: abs(rank[x[1]] - mine_r))[0][0],
        "others": len(others),
    }


def _outliers(ref: str, contacts: list[dict]) -> list[dict]:
    """The tags where this person is the only one holding their position.

    Not "how do you differ from the average" — an average over five people rating
    six tags is noise. The question worth answering is the one the group actually
    runs into: is there something only YOU want, or only you would rather skip.
    So a row is reported only when this person's rating is the unique extreme in
    either direction, which is exactly the case where the group's plan and this
    person's preference pull apart.

    Silence is not a position: a member who never rated a tag is not counted on
    either side, and a tag nobody else rated produces no row at all.
    """
    me = next((c for c in contacts if c.get("slug") == ref), None)
    if not me or len(contacts) < _api._OUTLIER_MIN_CREW:
        return []

    rank = prefs.RATING_RANK
    out = []
    for grid_key, prefs_key in (("interests", "travel_prefs"), ("cuisines", "food_prefs")):
        for tag in _outlier_grid_tags(contacts, prefs_key, grid_key):
            row = _outlier_row(ref, me, contacts, prefs_key, grid_key, tag, rank)
            if row is not None:
                out.append(row)
    # Widest gaps first: a lone "must" among neutrals matters more than a lone
    # "want" among neutrals, and the page shows a handful, not all nineteen.
    out.sort(key=lambda r: (-abs(rank[r["yours"]] - 2), r["tag"]))
    return out


@_api.bp.route("/api/prefs/account", methods=["GET"])
def api_account():
    """Everything the account page renders, in one call.

    Deliberately NOT folded into prefs_state: that runs on the gate's own render
    and on every form submit, and this reads the wiki, the crew of every trip the
    person is on, and their card look. The wall stays cheap; the account page
    pays for what it shows.

    Same identity rule as every other route in this block — pinned sessions (a
    guest on the mirror, Hub with "view as" on) get themselves no matter what the
    query string says, and only an unpinned Hub may name someone.
    """
    ref, locked = _submit_ref(request.args)
    if not ref:
        return jsonify({"error": "nobody is signed in"}), 403

    got = db.prefs_for_refs([ref]).get(ref, {})
    contact = prefs.contact_for_member(_api._VAULT_ROOT, {"contact_slug": ref}) or {}
    travel = _api._denoise(
        _api._live_prefs(contact.get("travel_prefs") or {}, got.get("travel", {}), "travel"), "travel"
    )
    food = _api._denoise(got.get("food", {}).get("prefs") or {}, "food")

    trip_ids = sorted(db.trips_for_slug(ref))
    trips = []
    crew: list[dict] = []
    seen = set()
    for tid in trip_ids:
        t = db.get_trip(tid)
        if not t:
            continue
        members = db.trip_members(tid) or []
        trips.append({
            "id": t["id"], "name": t.get("name", ""),
            "destination": t.get("destination", ""),
            "start_date": t.get("start_date", ""), "end_date": t.get("end_date", ""),
            "crew": len(members),
        })
        # One entry per PERSON across every trip, not per membership: someone on
        # two of your trips is one opinion, and counting them twice would let a
        # frequent co-traveller decide on their own whether you are the outlier.
        for m in members:
            key = db.member_key(m.get("name", ""), m.get("contact_slug") or "")
            if key in seen:
                continue
            seen.add(key)
            node = prefs.contact_for_member(_api._VAULT_ROOT, m)
            sub = db.prefs_for_refs([key]).get(key, {})
            if node is None and not sub:
                continue
            base = (node or {}).get("travel_prefs") or {}
            crew.append({
                "slug": key,
                "name": (node or {}).get("name") or m.get("name", ""),
                "travel_prefs": _api._denoise(_api._live_prefs(base, sub.get("travel", {}), "travel"), "travel"),
                "food_prefs": _api._denoise(sub.get("food", {}).get("prefs") or {}, "food"),
            })

    return jsonify({
        **prefs_state(ref, _api._preview_name()),
        "locked": locked,
        "me": {
            "name": contact.get("name") or _api._preview_name() or ref,
            "summary": contact.get("summary") or "",
            "aliases": contact.get("aliases") or [],
            "path": contact.get("path") or "",
            "travel_prefs": travel,
            "food_prefs": food,
            "filled": sorted(got),
        },
        "card": db.card_look(ref),
        "unlocked": _card_unlocked(ref),
        "variants": _api.CARD_VARIANTS,
        "unlocks": _api.CARD_UNLOCKS,
        "trips": trips,
        "outliers": _outliers(ref, crew),
        "scales": prefs.SCALES,
        "labels": prefs.LABELS,
    })


@_api.bp.route("/api/prefs/submit", methods=["POST"])
def api_submit_prefs():
    """Store one form, filled in on the board instead of on Google.

    The whole point of this route is the line that reads the ref: on the public
    mirror it comes off the guest_codes row this session unlocked, so the body
    cannot name anyone. Aaron posting Leo's key writes Aaron's own row, because
    the key in the body is never read there at all.

    A dashboard submission is one row per (kind, member), updated in place —
    `dash:<ref>`. Google's rows keep accumulating because each submission has its
    own response id and Google will not update one; here there is no reason to
    grow a row per edit, and newest-wins still decides between the two sources.
    """
    body = request.get_json(silent=True) or {}
    kind = str(body.get("kind", ""))
    if kind not in forms_intake.KINDS:
        return jsonify({"error": "unknown form"}), 400
    ref, locked = _submit_ref(body)
    if not ref:
        return jsonify({"error": "nobody is signed in"}), 403
    answers = forms_intake.clean_submission(kind, body.get("answers") or {})
    if not answers:
        return jsonify({"error": "nothing to save"}), 400
    db.save_form_responses(kind, [{
        "ref": ref,
        "name": str(body.get("name", "")).strip()[:80],
        "response_id": f"dash:{ref}",
        "submitted_at": datetime.datetime.now(datetime.timezone.utc)
                        .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "prefs": answers,
    }])
    return jsonify(prefs_state(ref))


@_api.bp.route("/api/prefs/me", methods=["GET"])
def api_my_prefs():
    """Who the viewer is, what they still owe, and the links to go do it.

    This is what the completion wall renders and what the crew tab's own portal
    reads. VIEWER is installed by the public process off the guest_codes row, so
    on Hub (no VIEWER) it answers with an empty ref and both forms unfilled —
    correct, because Hub is not a guest.
    """
    viewer = current_app.config.get("VIEWER")
    ref = str((viewer() if callable(viewer) else "") or "")
    return jsonify(prefs_state(ref))


def _bound_key() -> str:
    """The member this session is pinned to, or "" when it is pinned to nobody.

    Two ways to be pinned, and they are the same fact wearing different clothes:
    the mirror installs VIEWER, which reads the key off the guest_codes row a
    passcode unlocked; Hub pins itself when "view as" is on. Sam on Hub with
    no preview running is pinned to nobody, which is what lets him reach any
    crew member's sheet.

    Every surface that asks "whose is this?" now asks here. It used to be asked
    three different ways — the template read the preview, the crew portal read
    only VIEWER, and the submit route read only VIEWER — which is why a preview
    showed the whole crew's portals instead of the one person being previewed.
    """
    viewer = current_app.config.get("VIEWER")
    if callable(viewer):
        return str(viewer() or "")
    return _api._preview_slug()


def _submit_ref(source) -> tuple[str, bool]:
    """Whose preferences this request may touch, and whether that was forced.

    Pinned (a guest on the mirror, or Hub with "view as" on) → that member, and
    nothing the caller sent is consulted. A guest posting someone else's key
    writes their own row, because the key in the body is never read.

    Unpinned (Sam on Hub, no preview) → the key comes from the request. That
    is the admin path: Hub is the private, password-gated port whose only caller
    is him, and fixing a crew member's typo has to be reachable somehow.

    Unpinned and NAMING NOBODY is Sam asking for his own, which is what the
    Hub topbar's preferences link sends. It used to answer "" and every route
    here then 403'd, so the one surface he owns was the one he could not open.
    The mirror never reaches this line — a guest is always pinned.

    Returns (member key, locked). `locked` is what the UI reads to say whose
    sheet this is; it never decides anything — the decision is the line above it.
    """
    bound = _bound_key()
    if bound or callable(current_app.config.get("VIEWER")):
        return bound, True
    return str(source.get("ref", "") or "").strip() or _api.ME_SLUG, False


def prefs_state(ref: str, name: str = "") -> dict:
    """The wall state: which forms are in, and what is still owed inside them.

    `done` and `owed` answer two different questions and both are needed. `done`
    is "has this person ever submitted this form", which is what the board's gate
    turns on — a submitted form opens the board and keeps it open. `owed` is
    "which questions on it have no answer the form would accept today", which is
    what the nag runs off, and it can be non-empty on a form that is `done`.

    That gap is not hypothetical: retiring the escape options on 2026-08-29 left
    seven live answers off-menu at once. Every completeness check in the app said
    those people were finished, because a row existed, while the group read
    quietly could not place them.
    """
    have = db.prefs_for_refs([ref]).get(ref, {}) if ref else {}
    forms = []
    for kind in forms_intake.KINDS:
        got = have.get(kind, {})
        forms.append({
            "kind": kind,
            "label": forms_intake.spec(kind)["label"],
            "done": kind in have,
            "submitted_at": got.get("submitted_at", ""),
            "url": _api.form_links(ref, name)[kind],
            # Empty on a form nobody has opened — "you owe 17 questions" is a
            # project, and "fill it in" already says everything that form needs.
            "owed": forms_intake.unanswered(kind, got.get("prefs") or {}) if kind in have else [],
        })
    owed_n = sum(len(f["owed"]) for f in forms)
    return {
        "ref": ref,
        "forms": forms,
        "complete": all(f["done"] for f in forms),
        # What the nag needs, computed once here so the account page and the
        # board cannot disagree about whether somebody is being chased.
        "owed_count": owed_n,
        "needs_attention": owed_n > 0 or not all(f["done"] for f in forms),
        "fix_minutes": forms_intake.FIX_MINUTES,
    }
