"""Guest trip intake routes (guest half) and the Hub's approval queue (Hub half).

Split out the same way api_access.py is: reaches trips.api and trips.db by
attribute at call time so a test's monkeypatch on either facade still lands.
Design: docs/specs/2026-10-12-friend-trip-intake-form-design.md.

Guest half: the form page and its POST. The mirror stays read-only to trip
content; the one allowance in public_gate._read_only_gate is this exact POST, and
it only ever inserts a pending row. Both routes are guest-only (config GUEST),
so Hub, which is Sam and not a guest, answers 404 rather than letting him
file a submission as a guest by accident. "view as" is a Hub preview, not the
mirror, so it is refused the same way.

Hub half: /api/intakes is withheld from the mirror (public_app._WITHHELD_PREFIXES),
because it lists every guest's submission across every trip.
"""

from __future__ import annotations

import threading

from flask import current_app, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from . import api as _api
from . import db, intake

_HOURLY_LIMIT = 20


def _guard():
    """The guest's member key, or (response, status) when this is not a guest."""
    if not current_app.config.get("GUEST", False):
        return None, (jsonify({"error": "not found"}), 404)
    key = _api._bound_key()
    if not key:
        return None, (jsonify({"error": "nobody is signed in"}), 403)
    return key, None


# ── Guest half ────────────────────────────────────────────────────────────────

@_api.bp.route("/<int:trip_id>/intake", methods=["GET"])
def intake_page(trip_id):
    key, bad = _guard()
    if bad:
        return bad
    if not db.get_trip(trip_id):
        return jsonify({"error": "not found"}), 404
    with db._conn() as conn:
        prefill = intake.prefill(conn, trip_id, key)
        base = intake.current_payload(conn, trip_id)
    intake._redact(base)
    return _api._no_store(_api.make_response(render_template(
        "trip-intake.html", guest=True,
        intake={"trip_id": trip_id, "prefill": prefill, "base": base})))


@_api.bp.route("/api/trips/<int:trip_id>/intake", methods=["POST"])
def api_submit_intake(trip_id):
    key, bad = _guard()
    if bad:
        return bad
    try:
        body = request.get_json(silent=True)
    except RequestEntityTooLarge:
        return jsonify({"error": "that submission is too large"}), 413
    if (not isinstance(body, dict) or not isinstance(body.get("payload"), dict)
            or not isinstance(body.get("base"), dict)):
        return jsonify({"error": "send {\"payload\": {...}, \"base\": {...}}"}), 400
    if not db.get_trip(trip_id):
        return jsonify({"error": "not found"}), 404
    with db._conn() as conn:
        if intake.count_recent(conn, key) >= _HOURLY_LIMIT:
            return jsonify({"error": "too many submissions this hour"}), 429
        try:
            iid = intake.submit(conn, trip_id, key, body["payload"], body.get("base"))
        except intake.IntakeError as e:
            return jsonify({"error": e.msg}), e.status
    return jsonify({"ok": True, "intake_id": iid})


# ── Hub half ──────────────────────────────────────────────────────────────────

def start_research(intake_id):
    """Kick the `trip-intake` scheduler job in a daemon thread so the approve
    click returns at once. The job claims whichever intake is queued, so the id
    is only for the log. A missing job (not configured yet) is logged and ignored."""
    try:
        import scheduler
        job = next((j for j in scheduler.load_config()["jobs"]
                    if j.get("skill") == "/trip-intake"), None)
    except Exception:
        _api.logger.warning("trip-intake: scheduler unavailable", exc_info=True)
        return
    if not job:
        _api.logger.warning("trip-intake: no trip-intake job configured (intake %s)", intake_id)
        return
    # The id rides on the prompt so this run claims the intake just approved.
    job = {**job, "skill": f"{job['skill']} {int(intake_id)}"}
    threading.Thread(target=scheduler.run_skill, args=(job,), daemon=True).start()


def _cross_site():
    """A refusal when this POST could have come from another site. A cross-site
    form cannot send JSON, and a cross-site fetch that does is preflighted and
    refused (Hub answers no CORS), so JSON plus Sec-Fetch-Site covers both."""
    if not request.is_json or request.headers.get("Sec-Fetch-Site", "none") not in ("same-origin", "none"):
        return jsonify({"error": "send this from the Hub page"}), 403
    return None


@_api.bp.route("/api/intakes", methods=["GET"])
def api_intakes():
    with db._conn() as conn:
        rows = intake.list_pending(conn)
    out = []
    for r in rows:
        trip = db.get_trip(r["trip_id"]) or {}
        out.append({"id": r["id"], "trip_id": r["trip_id"], "trip_name": trip.get("name", ""),
                    "guest_key": r["guest_key"], "submitted_at": r["submitted_at"],
                    "diff": r["diff"], "research_status": r["research_status"]})
    return jsonify(out)


@_api.bp.route("/api/intakes/<int:intake_id>/approve", methods=["POST"])
def api_approve_intake(intake_id):
    if bad := _cross_site():
        return bad
    try:
        log = intake.apply(db._db_path, intake_id)
    except intake.IntakeError as e:
        return jsonify({"error": e.msg}), e.status
    if log.get("error"):
        return jsonify({"error": log["error"], "apply_log": log}), 409
    with db._conn() as conn:
        row = intake._load(conn, intake_id)
    if row["research_status"] == "queued":
        start_research(intake_id)
    return jsonify({"ok": True, "apply_log": log})


@_api.bp.route("/api/intakes/<int:intake_id>/reject", methods=["POST"])
def api_reject_intake(intake_id):
    if bad := _cross_site():
        return bad
    try:
        with db._conn() as conn:
            intake.reject(conn, intake_id)
    except intake.IntakeError as e:
        return jsonify({"error": e.msg}), e.status
    return jsonify({"ok": True})
