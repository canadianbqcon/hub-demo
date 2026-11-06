"""Crew preferences and the two Google Forms: the crew tab's data, the form
bridge, the account page's completion wall, and the address search.

Split from trips/api.py (Task 4 of the 2026-09-24 trips-split plan; the card
cosmetics, outlier rail and account-page routes moved on into api_account.py,
since this file came in over 500 lines by itself). Reaches every trips.api
global through the `_api` alias and every trips.db function through `db`,
both by attribute at call time (never `from .api import ...` /
`from .db import ...`), so a test's monkeypatch on either facade still lands
here. `sync_form_responses` writes `_api._last_sync` (Rule 1: the throttle
state stays on the facade). `_bound_key`, `_submit_ref` and `prefs_state`
live in api_account.py and are reached back here as `_api.<name>` — the same
cross-section rule as any other facade attribute. See
dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

import time

from flask import current_app, jsonify, make_response, render_template, request

from . import api as _api
from . import db
from . import forms_intake
from . import preferences as prefs


# ── Crew preferences ──────────────────────────────────────────────────────────


def _denoise(payload: dict, kind: str) -> dict:
    out = dict(payload or {})
    for field in _api._FREE_TEXT[kind]:
        if field in out and prefs.is_noise(out[field]):
            out[field] = ""
    if kind == "food" and out.get("diets"):
        # "No restrictions" is the answer to the checkbox, not a restriction.
        out["diets"] = [d for d in out["diets"] if d != "No restrictions"]
    return out


def _form_keys(kind: str) -> set[str]:
    """Every key the form asks about, read off the schema rather than listed.

    A second hand-kept list is how the card and the form drift apart, which is
    the whole bug this exists to close.
    """
    return {
        q["key"]
        for section in forms_intake.schema(kind)["sections"]
        for q in section["questions"]
    }


def _live_prefs(node_prefs: dict, got: dict, kind: str) -> dict:
    """A member's current answers: the wiki node, corrected by their submission.

    A blank answer is a CLEAR only on a form that showed the person their current
    answer first. The board's own form is prefilled, so leaving a box empty there
    means "I no longer have one" and the node's value has to go. A Google form
    opens blank every time, so a skipped question means nothing at all — Leo's
    second May submission skipped absolute_nos, and reading that as a clear would
    have erased "No haunted houses" he never touched.

    Hence: a `dash:` submission is authoritative across the whole form; a Google
    one stays a per-key overlay.
    """
    base = dict(node_prefs or {})
    sub = got.get("prefs") or {}
    if not sub:
        return base
    if str(got.get("response_id", "")).startswith("dash:"):
        keys = _form_keys(kind)
        # `<key>_other` is the companion of a form key, so it clears with it.
        base = {
            k: v for k, v in base.items()
            if k not in keys and k.removesuffix("_other") not in keys
        }
    return {**base, **sub}


@_api.bp.route("/api/trips/<int:trip_id>/preferences", methods=["GET"])
def api_trip_preferences(trip_id):
    """Crew preferences, plus each member's own portal into the two forms.

    Two sources feed this, in one order that never varies: the wiki contact node
    is the base, and a submitted form response overlays it. The overlay is what
    makes "fill it in again to change your answers" true — a resubmission lands
    in member_prefs and nowhere else, so a node-wins merge would show the old
    answers back on the board and look like the form had not saved.

    Someone with no contact node is no longer automatically preference-less:
    if they have submitted, they get a card built from the submission alone. That
    is the Karim case, and it is the whole point of handing out the form.
    """
    members = db.trip_members(trip_id)
    if members is None:
        return jsonify({"error": "not found"}), 404

    keys = {m["id"]: db.member_key(m.get("name", ""), m.get("contact_slug") or "")
            for m in members}
    submitted = db.prefs_for_refs(list(keys.values()))

    # A prefilled link carries whose answers the submission becomes, so handing a
    # guest everyone's links would let any of them overwrite anyone else's
    # allergies. On the public process VIEWER is installed and only the viewer's
    # own link goes out; on Hub it is absent and Sam gets all of them, which
    # is how he sends someone theirs in the first place.
    # Pinned → only that member's portal goes out. On the mirror that stops one
    # guest reaching another's form; in a Hub preview it is what makes "view as
    # Leo" show Leo's crew tab rather than everyone's.
    bound = _api._bound_key()
    only_ref = bound if (bound or callable(current_app.config.get("VIEWER"))) else None

    def _portal(ref, name):
        if only_ref is not None and ref != only_ref:
            return None
        return _api.prefs_state(ref, name)

    member_contacts = []
    members_without_contact = []
    for m in members:
        ref = keys[m["id"]]
        got = submitted.get(ref, {})
        contact = prefs.contact_for_member(_api._VAULT_ROOT, m)
        if contact is None and got:
            # Enough of a contact shape for the crew card to render, built from
            # the submission alone. No summary and no aliases: those are things a
            # person writes about someone, not answers to a form.
            contact = {
                "path": "", "slug": ref, "name": m.get("name", ""), "email": "",
                "aliases": [], "summary": "", "travel_prefs": {}, "body": "",
            }
        if contact is None:
            members_without_contact.append({
                "member_id": m["id"], "name": m.get("name", ""),
                "forms": _portal(ref, m.get("name", "")),
                "filled": sorted(got),
                "card": db.card_look(ref),
            })
            continue
        merged = _live_prefs(contact.get("travel_prefs") or {}, got.get("travel", {}), "travel")
        member_contacts.append({
            **contact,
            "member_id": m["id"],
            "travel_prefs": _denoise(merged, "travel"),
            "food_prefs": _denoise(got.get("food", {}).get("prefs") or {}, "food"),
            "forms": _portal(ref, m.get("name", "")),
            # Which forms this person has ANSWERED, for everyone — separate from
            # `forms`, which is the portal and is access-controlled to the bound
            # viewer. The card's shimmer and border unlock off "did they answer",
            # a public fact about the crew; reading it off the portal meant the
            # mirror stripped every other member's cosmetics along with their
            # links. Names only, never the answers.
            "filled": sorted(got),
            "card": db.card_look(ref),
        })
    return jsonify(
        {
            "members": member_contacts,
            "members_without_contact": members_without_contact,
            "aggregate": prefs.aggregate_preferences(member_contacts),
            # The order behind every ordinal answer, so the rail and the cards can
            # draw where a value SITS rather than only printing what it is called.
            # Shipped rather than mirrored in JS: the ranks the rollups above are
            # computed with and the ranks the page draws have to be the same ranks,
            # or a row lights the wrong stop and nothing says so.
            "scales": prefs.SCALES,
        "labels": prefs.LABELS,
        }
    )


# ── Form preferences (the two Google Forms) ───────────────────────────────────
#
# The forms stay on Google; this is the bridge. A guest opens a prefilled link,
# fills it in there, and a sync pulls the response back into member_prefs. See
# forms_intake for why the responses are attributed by a prefilled ref rather
# than by the name people type.


def form_links(ref: str, name: str = "") -> dict:
    """Prefilled links to both forms for one member key.

    Never raises: this rides along on the crew payload, and a Google hiccup must
    not be able to blank the crew tab. Without a cached ref question id the link
    is still the right form, just unattributed — which the sync then reports as
    unmatched rather than silently misfiling.
    """
    out = {}
    for kind in forms_intake.KINDS:
        try:
            out[kind] = forms_intake.prefill_url(kind, ref, name)
        except Exception:
            _api.logger.exception("form link failed for %s/%s", ref, kind)
            out[kind] = forms_intake.spec(kind)["responder"]
    return out


def sync_form_responses(force: bool = False) -> dict:
    """Pull both forms into member_prefs. Throttled unless forced."""
    now = time.monotonic()
    if not force and now - _api._last_sync < _api._SYNC_MIN_GAP:
        return {"skipped": "just synced", "throttled": True}
    _api._last_sync = now
    svc = forms_intake._service()
    result = {}
    for kind in forms_intake.KINDS:
        result[kind] = db.save_form_responses(kind, forms_intake.fetch_responses(kind, svc))
    return result


@_api.bp.route("/api/prefs/sync", methods=["POST"])
def api_sync_prefs():
    try:
        return jsonify(sync_form_responses())
    except Exception as e:
        _api.logger.exception("prefs sync failed")
        return jsonify({"error": f"could not reach the forms — {e}"}), 502


@_api.bp.route("/api/prefs/unmatched", methods=["GET"])
def api_unmatched_prefs():
    """Submissions with nobody attached. Hub only — it is Sam's to resolve."""
    return jsonify(db.unmatched_responses())


@_api.bp.route("/api/prefs/unmatched", methods=["PATCH"])
def api_claim_pref():
    data = request.get_json(force=True, silent=True) or {}
    kind = str(data.get("kind", ""))
    rid = str(data.get("response_id", ""))
    ref = str(data.get("ref", "")).strip()
    if kind not in forms_intake.KINDS or not rid or not ref:
        return jsonify({"error": "need kind, response_id and ref"}), 400
    if not db.claim_response(kind, rid, ref):
        return jsonify({"error": "no such response"}), 404
    return jsonify({"ok": True})


@_api.bp.route("/preferences")
def preferences_page():
    """The account page, on whichever surface asked.

    The mirror already served this at /gate/prefs and still does. Putting it on
    the blueprint gives Hub the same page from the same file rather than a
    second copy — which is the same reason the mirror runs the trips blueprint
    instead of a mirror of it.

    It is still the completion WALL when a form is outstanding: same page, with
    the gate strip lit and the board still shut. "You owe two forms" and "you want
    to change your card" are the same screen with different things pressing, and a
    second template would be the same markup kept in step by hand.

    `ref` selects the member, and is honoured only when this session is pinned to
    nobody. A guest, or Hub with "view as" running, gets their own regardless of
    what the query string says.
    """
    ref, locked = _api._submit_ref(request.args)
    return make_response(render_template(
        "account.html",
        state=_api.prefs_state(ref, _api._preview_name()),
        # The sign-out link is the mirror's; on Hub it points at a route that only
        # exists over there. It also decides whether the details section renders —
        # see the `me` note on the mirror's own copy of this route.
        wall_mode="guest" if current_app.config.get("GUEST", False) and not _api._preview_slug()
                  else "hub",
        locked=locked,
    ))


@_api.bp.route("/api/prefs/form/<kind>", methods=["GET"])
def api_pref_form(kind):
    """The form to render, plus whatever this member already answered.

    `ref` is a query parameter ONLY on Hub, where the caller is Sam and the
    crew tab needs to open someone's sheet. On the public mirror VIEWER is
    installed and the parameter is ignored outright, so a guest can only ever
    load their own — the same rule the submit route enforces on the way back in.
    """
    if kind not in forms_intake.KINDS:
        return jsonify({"error": "unknown form"}), 404
    ref, locked = _api._submit_ref(request.args)
    if not ref:
        return jsonify({"error": "nobody is signed in"}), 403
    have = db.prefs_for_refs([ref]).get(ref, {}).get(kind, {})
    # Prefilled from what the CREW CARD shows, not from the submission alone.
    # A field that lives only on the wiki node used to be invisible here, so it
    # could never be corrected or cleared — and saving the form then looked like
    # it had not saved, because the card kept printing it.
    node = prefs.contact_for_member(_api._VAULT_ROOT, {"contact_slug": ref}) or {}
    base = (node.get("travel_prefs") or {}) if kind == forms_intake.TRAVEL else {}
    answers = _live_prefs(base, have, kind)
    return jsonify({
        "ref": ref,
        "locked": locked,
        "schema": forms_intake.schema(kind),
        "answers": answers,
        # Computed off the SAME answer set the editor is about to render, not off
        # the raw submission: the wiki node merges in on top, so a question the
        # form will show as filled must not be marked owed underneath it.
        "owed": forms_intake.unanswered(kind, answers),
        "submitted_at": have.get("submitted_at", ""),
        # So the option row can show that it IS a scale while it is being
        # answered, in the same order the read-back and the group rail use.
        "scales": prefs.SCALES,
        "labels": prefs.LABELS,
    })


