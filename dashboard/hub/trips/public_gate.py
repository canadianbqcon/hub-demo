"""The keypad, the completion wall, and the per-request access checks.

Split from trips/public_app.py (Task 6 of the 2026-09-24 trips-split plan).
Reaches every public_app global through the `_pa` alias at call time (never
`from .public_app import ...`), so a test's monkeypatch on the facade (its
`vault_root`, `_LL_TRIP_ID`, `_FAILS`, rate-limit windows, prefix lists) still
lands here. See dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

import time

from flask import jsonify, make_response, redirect, render_template, request, session

from . import api as trips_api
from . import db as trips_db
from . import public_app as _pa


def _json_body() -> dict | None:
    """The parsed body, or None when this was not really a JSON post.

    Checking the content type is what keeps the two writable routes off-limits to
    a cross-site HTML form: a form can only send urlencoded, multipart or plain
    text, and application/json forces a preflight no hostile page will be granted.
    `get_json(force=True)` skipped that check and parsed whatever arrived.
    """
    if request.mimetype != "application/json":
        return None
    return request.get_json(silent=True) or {}


def _client_ip() -> str:
    """Best-effort client identity.

    Tailscale Funnel proxies through tailscaled, so the peer is often loopback and
    the real client only appears in X-Forwarded-For — which anything that reaches
    this port directly can forge. Hence "best-effort": this partitions honest
    callers, it does not resist a determined one. That trade is recorded in the
    design spec's rate-limiting section; scoping is what limits the damage, and
    _pa._FAILS is what stops a caller renaming itself out of the throttle.

    Taking the LAST element of the chain is the point: tailscaled appends the
    address it saw, so whatever the client wrote sits to the left of it.
    """
    peer = request.remote_addr or ""
    fwd = request.headers.get("X-Forwarded-For", "")
    if peer in ("127.0.0.1", "::1", "localhost") and fwd:
        return fwd.split(",")[-1].strip()
    return peer


def _too_many(bucket: dict[str, list[float]], key: str, limit: int, window: int) -> bool:
    now = time.time()
    hits = [t for t in bucket.get(key, []) if now - t < window]
    bucket[key] = hits
    return len(hits) >= limit


def _record(bucket: dict[str, list[float]], key: str) -> None:
    bucket.setdefault(key, []).append(time.time())


def _guest_code() -> dict | None:
    """The unlocked guest, re-read from the DB on every request.

    The cookie carries a row id and nothing else. Trusting the cookie's own
    contents would make revocation impossible — denying someone would not take
    effect until their cookie expired. Reading the row means a denied code stops
    working on the guest's very next click.
    """
    code_id = session.get("guest_code_id")
    if not code_id:
        return None
    row = trips_db.guest_code_by_id(code_id)
    if not row or row.get("status") != "approved":
        session.pop("guest_code_id", None)
        return None
    return row


def _prefs_done(guest: dict) -> bool:
    """Has this guest submitted both forms?

    A DB read, never a Google call: this runs on every request, and the sync that
    keeps it current is the guest's own click on the wall (plus whatever Sam
    runs from Hub). An unlinked code — no member key — cannot be matched to a
    submission at all, so it is treated as unfinished rather than waved through;
    the approve trigger already makes that state unreachable for a live code.
    """
    ref = (guest.get("contact_slug") or "").strip()
    if not ref:
        return False
    have = trips_db.prefs_for_refs([ref]).get(ref, {})
    return all(k in have for k in ("travel", "food"))


def _allowed_trips() -> set[int]:
    guest = _guest_code()
    return trips_db.trips_for_slug(guest["contact_slug"]) if guest else set()


def _viewer_key() -> str:
    """The member key of whoever unlocked this session.

    Read off the guest_codes row, never off anything the browser sent, and it
    is the same key trips_for_slug already scopes on, so the board can only
    put someone first who was already allowed to see the trip. Ordering only:
    it hides nothing and reveals nothing on its own.
    """
    guest = _guest_code()
    return (guest or {}).get("contact_slug") or ""


def _read_only_gate():
    # Withheld first. Method-checking first would answer a DELETE to a
    # withheld path with 405, which confirms the route exists.
    if request.path.startswith(_pa._WITHHELD_PREFIXES):
        return {"error": "not found"}, 404
    if (request.method not in ("GET", "HEAD", "OPTIONS") and request.path not in _pa._WRITABLE_PATHS
            and not (request.method == "POST" and _pa._INTAKE_POST.match(request.path))):
        return {"error": "read-only"}, 405
    return None


def _gate():
    """Locked visitors see the keypad; unlocked ones see only their trips.

    One hook covers every trip-scoped route because they all name the id
    `trip_id` in the path, so `view_args` is a complete list of what is being
    asked for. A per-route check would be a thing each future route has to
    remember, and forgetting it is silent.
    """
    if request.path in _pa.public_area.PUBLIC_EXACT or request.path.startswith(_pa._PUBLIC_PREFIXES):
        return None
    guest = _guest_code()
    if not guest:
        if request.path.startswith("/trips/api/"):
            return jsonify({"error": "locked"}), 403
        return redirect("/gate")
    # Every authenticated hit is this person being online, which is what the
    # access panel claims to show. Before the prefs wall on purpose: somebody
    # held on the form is here, and the panel saying otherwise is how a guest
    # stuck on it looks like a guest who wandered off. Throttled in SQL, so
    # the page's own API calls do not each cost a write.
    trips_db.touch_guest_code(guest["id"], _pa._SEEN_THROTTLE_MINUTES)
    # Forms before the board. The wall itself, its check, and the assets it
    # loads are exempt or there would be nowhere to satisfy it from. The
    # board's own API is held back too: leaving it reachable would mean the
    # page redirects while its data still loads, which is not a gate, it is
    # a flicker.
    if not request.path.startswith(_pa._PREFS_EXEMPT) and not _prefs_done(guest):
        if request.path.startswith("/trips/api/"):
            return jsonify({"error": "preferences incomplete"}), 403
        return redirect("/gate/prefs")
    trip_id = (request.view_args or {}).get("trip_id")
    if trip_id is not None and trip_id not in _allowed_trips():
        # 404, never 403: "forbidden" would confirm the trip exists. A trip
        # that is not theirs and a trip that does not exist answer alike,
        # because this runs ahead of the view that would otherwise redirect
        # for a missing one and turn the difference into a probe.
        return jsonify({"error": "not found"}), 404
    return None


# ── The gate ──────────────────────────────────────────────────────────────


def gate():
    if _guest_code():
        return redirect("/trips/")
    return make_response(render_template("gate.html"))


def gate_submit():
    ip = _client_ip()
    data = _json_body()
    if data is None:
        return jsonify({"error": "send json"}), 415
    if _too_many(_pa._FAILS, ip, _pa._FAIL_LIMIT, _pa._FAIL_WINDOW):
        return jsonify({"error": "too many tries — wait a few minutes"}), 429
    if trips_db.gate_frozen_until():
        # Deliberately worded like the per-IP cooldown above. Which of the two
        # you hit — your address, or the whole keypad — is the one fact a
        # guesser could actually use, so both answers read the same.
        _pa.logger.error("gate: keypad frozen, attempt from %s refused", ip)
        return jsonify({"error": "too many tries — wait a few minutes"}), 429
    code = str(data.get("code", ""))
    row = trips_db.guest_code_by_code(code) if _pa._CODE_RE.match(code) else None
    if not row:
        _record(_pa._FAILS, ip)
        # Strikes are NOT cleared by a later success. One guess landing is not
        # evidence the sweep around it was honest — only Sam clears them.
        state = trips_db.record_gate_failure()
        if state.get("frozen_until"):
            _pa.logger.error(
                "gate: strike %s — keypad frozen until %s%s",
                state["strikes"], state["frozen_until"],
                " (needs clearing from the access panel)"
                if state["strikes"] >= trips_db._HARD_STOP_STRIKE else "",
            )
        _pa.logger.warning("gate: wrong code from %s", ip)
        return jsonify({"error": "that code doesn't work"}), 401
    _pa._FAILS.pop(ip, None)
    session.permanent = True
    session["guest_code_id"] = row["id"]
    # Unconditional: every unlock through this door is a real person typing a
    # real code, so last_seen means what it says. Sam's "view as" does not
    # come through here at all — it is a preview on Hub (trips/api.py), which
    # never touches this process or this row.
    trips_db.touch_guest_code(row["id"])
    # Where the code drops you. Straight onto the board unless this person
    # owes answers — a missing form, or (the case nothing used to catch) a
    # submitted one holding values the questions no longer offer. Then the
    # wall comes first, because the sign-in is the one moment their attention
    # is already here. It is a redirect, not a lock: _gate still lets a filled
    # form through, so somebody at the airport can leave the wall and read the
    # board. Notify, not block.
    state = trips_api.prefs_state(row.get("contact_slug") or "")
    return jsonify({
        "ok": True,
        "next": "/gate/prefs" if state["needs_attention"] else "/trips/",
    })


def gate_prefs():
    """The account page, which is also the completion wall.

    One page for both jobs on purpose. "You still owe two forms" and "you
    want to change your card" are the same screen with different things
    pressing, and a second template would be the same markup kept in step by
    hand. While a form is outstanding the gate strip is lit and _gate above
    keeps the board shut; once both are in, the strip goes and this is where
    a guest changes their details, their answers and how their card looks.
    """
    guest = _guest_code()
    if not guest:
        return redirect("/gate")
    return make_response(render_template(
        "account.html",
        state=trips_api.prefs_state(guest.get("contact_slug") or "", guest.get("name") or ""),
        # Their own signup row, so the wall can let them fix it. Hub renders
        # this template with `me` absent — Sam edits the same four fields
        # from the access panel, and a preview is not the previewed person.
        me={k: guest.get(k) or "" for k in trips_db.GUEST_FIELDS},
        # The trips the intake form may open, one link each (trips/api_intake.py).
        intake_trips=[t for t in map(trips_db.get_trip, sorted(trips_db.trips_for_slug(trips_api._bound_key() or ""))) if t],
    ))


def gate_me():
    """Let a guest correct their own name, phone, email and address.

    The row is found from the session, never from the body, so this is the
    same shape as the prefs submit next to it: there is no subject to send
    and therefore no one else's record to reach. `contact_slug` is not
    touched — it is the join key every submission and every trip scope hangs
    off, and it is Sam's to set from the access panel.

    Same validation as /gate/request for the four fields it shares with it;
    length caps and an @-shaped email, nothing stricter (see the notes on
    _pa._MAX_PHONE). Address is the one optional field — the keypad never asks
    for it, so requiring it here would lock an existing guest out of fixing
    their own phone number.

    Address is stored beside the phone and the email and is read back only
    by its owner and by Sam: nothing on the shared board prints it.
    """
    guest = _guest_code()
    if not guest:
        return jsonify({"error": "locked"}), 403
    data = _json_body()
    if data is None:
        return jsonify({"error": "send json"}), 415
    first = str(data.get("first_name", "")).strip()
    last = str(data.get("last_name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    email = str(data.get("email", "")).strip()
    address = str(data.get("address", "")).strip()
    if not first or len(first) > _pa._MAX_NAME:
        return jsonify({"error": f"give a first name, under {_pa._MAX_NAME} characters"}), 400
    if not last or len(last) > _pa._MAX_NAME:
        return jsonify({"error": f"give a last name, under {_pa._MAX_NAME} characters"}), 400
    if not phone or len(phone) > _pa._MAX_PHONE:
        return jsonify({"error": f"give a phone number, under {_pa._MAX_PHONE} characters"}), 400
    if len(email) > _pa._MAX_EMAIL or not _pa._EMAIL_RE.match(email):
        return jsonify({"error": "give an email that looks like one"}), 400
    if len(address) > _pa._MAX_ADDRESS:
        return jsonify({"error": f"keep the address under {_pa._MAX_ADDRESS} characters"}), 400
    row = trips_db.set_guest_fields(guest["id"], {
        "first_name": first, "last_name": last, "phone": phone,
        "email": email, "address": address,
    })
    return jsonify({k: row.get(k) or "" for k in trips_db.GUEST_FIELDS})


def gate_logout():
    # A GET so the topbar can be a plain link. Worst case someone is tricked
    # into being signed out of a friends-only itinerary and types four digits
    # again; that is not worth a form and a token.
    session.pop("guest_code_id", None)
    return redirect("/gate")


def gate_request():
    ip = _client_ip()
    if _too_many(_pa._SIGNUPS, ip, _pa._SIGNUP_LIMIT, _pa._SIGNUP_WINDOW):
        return jsonify({"error": "too many requests — try later"}), 429
    data = _json_body()
    if data is None:
        return jsonify({"error": "send json"}), 415
    first = str(data.get("first_name", "")).strip()
    last = str(data.get("last_name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    email = str(data.get("email", "")).strip()
    code = str(data.get("code", ""))
    if not first or len(first) > _pa._MAX_NAME:
        return jsonify({"error": f"give a first name, under {_pa._MAX_NAME} characters"}), 400
    if not last or len(last) > _pa._MAX_NAME:
        return jsonify({"error": f"give a last name, under {_pa._MAX_NAME} characters"}), 400
    if not phone or len(phone) > _pa._MAX_PHONE:
        return jsonify({"error": f"give a phone number, under {_pa._MAX_PHONE} characters"}), 400
    if len(email) > _pa._MAX_EMAIL or not _pa._EMAIL_RE.match(email):
        return jsonify({"error": "give an email that looks like one"}), 400
    if not _pa._CODE_RE.match(code):
        return jsonify({"error": "pick four digits"}), 400
    if trips_db.pending_guest_code_count() >= _pa._MAX_PENDING:
        # About queue depth, never about this code — see below.
        return jsonify({"error": "too many requests pending — try later"}), 429
    _record(_pa._SIGNUPS, ip)
    trips_db.request_guest_code(first, last, code, phone=phone, email=email)
    # Always the same answer, even when that code is already someone's. Saying
    # "taken" here would let anyone walk 0000-9999 and read off the live codes
    # without a single wrong guess at the keypad. Sam sees the clash when
    # he approves, where telling him costs nothing.
    return jsonify({"ok": True})


def gate_out():
    session.pop("guest_code_id", None)
    return redirect("/gate")
