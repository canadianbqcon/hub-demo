"""Guest access routes: the share URL, guest codes, the gate-freeze, roster and
crew members.

Split from trips/api.py (Task 4 of the 2026-09-24 trips-split plan). Reaches
every trips.api global through the `_api` alias and every trips.db function
through `db`, both by attribute at call time (never `from .api import ...` /
`from .db import ...`), so a test's monkeypatch on either facade still lands
here. See dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from flask import jsonify, request

from . import api as _api
from . import db


# ── Guest codes — Hub only ────────────────────────────────────────────────────
# These live on the shared blueprint, so they exist in the public process too.
# The writes are already dead there (non-GET is rejected), but the GET would
# publish every guest's name and code to the internet, so public_app.py withholds
# the whole prefix. If that guard is ever removed, this becomes a data leak.


@_api.bp.route("/api/share-url", methods=["GET"])
def api_share_url():
    """The live public share link, or null when nothing is being shared.

    Read straight out of Tailscale rather than stored, so /unshare taking the
    funnel down is reflected on the next click instead of handing out a dead
    URL. Called on click, not at render — the subprocess is too slow to sit in
    the landing page's path.
    """
    # Windows binary first: on the PC the WSL `tailscale` on PATH is the rivera-wsl
    # node, which never carries the funnel, so asking it always answered null.
    win = "/mnt/c/Program Files/Tailscale/tailscale.exe"
    ts = win if os.path.exists(win) else (shutil.which("tailscale") or "tailscale")
    try:
        out = subprocess.run([ts, "serve", "status", "--json"],
                             capture_output=True, text=True, timeout=8).stdout
        funnel = json.loads(out).get("AllowFunnel") or {}
    except Exception:
        _api.logger.warning("share-url: couldn't read tailscale serve status", exc_info=True)
        return jsonify({"url": None})
    for hostport, on in sorted(funnel.items()):
        if on:
            return jsonify({"url": "https://%s/" % hostport})
    return jsonify({"url": None})


@_api.bp.route("/api/guest-codes", methods=["GET"])
def api_guest_codes():
    """The signup requests plus what Sam needs to action them: the roster of
    people a code can be linked to, and the failed-attempt counter."""
    roster = db.roster()
    # Everyone on the roster is pickable, contact node or not — plenty of crew
    # were typed straight into a trip and never got one.
    keys = [db.member_key(p.get("name", ""), p.get("contact_slug") or "") for p in roster]
    trips = db.trips_by_key(keys)   # one query, not one connection per person
    people = [
        {
            "contact_slug": key,
            "name": person.get("name", ""),
            "trip_ids": sorted(trips.get(key, ())),
        }
        for person, key in zip(roster, keys, strict=True)
    ]
    return jsonify({
        "requests": db.list_guest_codes(),
        "people": people,
        "stats": db.gate_stats(),
    })


@_api.bp.route("/api/guest-codes/<int:code_id>", methods=["PATCH"])
def api_patch_guest_code(code_id: int):
    """Approve/re-link a row, change its four digits or who it belongs to — any
    combination, in one call."""
    data = request.get_json(force=True, silent=True) or {}
    idents = {k: data[k] for k in db.GUEST_FIELDS if k in data}
    if not idents and "code" not in data and "status" not in data and "contact_slug" not in data:
        return jsonify({"error": "nothing to change"}), 400
    try:
        row = None
        if idents:
            row = db.set_guest_fields(code_id, idents)
        if "code" in data:
            row = db.set_guest_code(code_id, str(data.get("code") or ""))
        if "status" in data or "contact_slug" in data:
            if data.get("status") != "approved":
                return jsonify({"error": "only 'approved' is settable here; deny uses DELETE"}), 400
            slug = (data.get("contact_slug") or "").strip()
            if not slug:
                return jsonify({"error": "pick who this code belongs to"}), 400
            row = db.approve_guest_code(code_id, slug)
        return jsonify(row)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409


@_api.bp.route("/api/guest-codes/<int:code_id>", methods=["DELETE"])
def api_deny_guest_code(code_id: int):
    db.deny_guest_code(code_id)
    return jsonify({"ok": True})


@_api.bp.route("/api/gate-freeze", methods=["DELETE"])
def api_clear_gate_freeze():
    """Reopen the keypad after the strike system shut it.

    Hub only — public_app withholds this prefix. Deliberately a person's decision
    rather than a longer timer: past the fifth strike the honest reading is that
    someone is walking the code space, and the right response is Sam looking
    at it, not the gate quietly letting them carry on.
    """
    return jsonify(db.clear_gate_freeze())


# ── Members ───────────────────────────────────────────────────────────────────


@_api.bp.route("/api/trips/roster", methods=["GET"])
def api_roster():
    """Everyone who has ever been on a trip, for the "add from roster" picker.

    `?exclude=<trip_id>` drops people already on that trip, so the picker only
    ever offers someone you can actually add.
    """
    raw = request.args.get("exclude", "")
    return jsonify(db.roster(int(raw) if raw.isdigit() else None))


@_api.bp.route("/api/trips/<int:trip_id>/members", methods=["POST"])
def api_add_member(trip_id):
    return jsonify(db.add_member(trip_id, request.get_json(force=True, silent=True) or {})), 201


@_api.bp.route("/api/trips/<int:trip_id>/members/<int:mid>", methods=["PATCH"])
def api_update_member(trip_id, mid):
    row = db.update_member(trip_id, mid, request.get_json(force=True, silent=True) or {})
    return jsonify(row) if row else (jsonify({"error": "not found"}), 404)


@_api.bp.route("/api/trips/<int:trip_id>/members/<int:mid>", methods=["DELETE"])
def api_delete_member(trip_id, mid):
    return jsonify({"ok": db.delete_member(trip_id, mid)})
