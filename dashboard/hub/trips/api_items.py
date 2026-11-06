"""Housing, flights, fare search, transport, expenses, grocery and activity
routes — the trip-item CRUD groups.

Split from trips/api.py (Task 3 of the 2026-09-24 trips-split plan; Task 4
moved `_FARE_KEEP` / `_FARE_TIMEOUT` / `_fare_note` in here from the facade,
to keep api.py under 500 lines — they are re-exported from `trips.api` the
same as everything else this file owns). Reaches every trips.api global
through the `_api` alias (`_api.gcal`, ...) and every trips.db function
through `db`, both by attribute at call time, never bound by value. See
dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

from flask import jsonify, request

from checklists import db as checklists_db

from . import api as _api
from . import db

# How many fares one search writes. Google returns dozens; a comparison table
# with dozens of near-identical rows is the same problem as no table at all.
_FARE_KEEP = 6
# A NYC-wide search is three sequential Google queries. The tool's own docs put
# that at 30-90s, so this is the ceiling before we give up rather than a target.
# ponytail: runs inline on the request thread. Single-user local dashboard, so a
# blocking minute is acceptable; if a second user ever appears, move it to a job.
_FARE_TIMEOUT = 180


def _fare_note(r, out, ret=""):
    """The context that makes a fare row comparable, folded into notes.

    ALL-IN vs sticker is the single most load-bearing fact the search produces
    (a ULCC base fare excludes the carry-on), so it is stated on every row where
    the two differ rather than left in a column nobody added.
    """
    bits = []
    if ret:
        bits.append(f"round trip, returns {ret} — price covers both legs, times below are the outbound")
    price, eff = r.get("price"), r.get("effective")
    if price is not None and eff is not None and abs(eff - price) > 0.5:
        bits.append(f"all-in ${eff:,.2f} vs ${price:,.2f} sticker")
    mins = out.get("duration_min")
    if mins:
        bits.append(f"{mins // 60}h{mins % 60:02d}m")
    stops = out.get("stops")
    if stops is not None:
        via = ", ".join(out.get("via") or [])
        bits.append("nonstop" if not stops else f"{stops} stop via {via}" if via else f"{stops} stop")
    if r.get("tier") == "skip":
        bits.append("connection buys nothing — a nonstop is within $50")
    if r.get("ulcc"):
        bits.append("ULCC, carry-on fee already added")
    bits.append(f"searched {datetime.date.today().isoformat()}")
    return " · ".join(bits)


@_api.bp.route("/api/trips/<int:trip_id>/housing", methods=["POST"])
def api_add_housing(trip_id):
    return jsonify(db.add_housing(trip_id, request.get_json(force=True, silent=True) or {})), 201


@_api.bp.route("/api/trips/<int:trip_id>/housing/<int:hid>", methods=["PATCH"])
def api_update_housing(trip_id, hid):
    row = db.update_housing(trip_id, hid, request.get_json(force=True, silent=True) or {})
    return jsonify(row) if row else (jsonify({"error": "not found"}), 404)


@_api.bp.route("/api/trips/<int:trip_id>/housing/<int:hid>", methods=["DELETE"])
def api_delete_housing(trip_id, hid):
    return jsonify({"ok": db.delete_housing(trip_id, hid)})


@_api.bp.route("/api/trips/<int:trip_id>/flights", methods=["POST"])
def api_add_flight(trip_id):
    return jsonify(db.add_flight(trip_id, request.get_json(force=True, silent=True) or {})), 201


@_api.bp.route("/api/trips/<int:trip_id>/flights/<int:fid>", methods=["PATCH"])
def api_update_flight(trip_id, fid):
    row = db.update_flight(trip_id, fid, request.get_json(force=True, silent=True) or {})
    return jsonify(row) if row else (jsonify({"error": "not found"}), 404)


@_api.bp.route("/api/trips/<int:trip_id>/flights/<int:fid>", methods=["DELETE"])
def api_delete_flight(trip_id, fid):
    return jsonify({"ok": db.delete_flight(trip_id, fid)})


def _fare_search_error(origin: str, dest: str, depart: str, ret: str) -> str:
    """What's wrong with this fare search request, or "" when it's clean."""
    if not (origin and dest and depart):
        return "origin, dest and depart are required"
    for label, value in (("depart", depart), ("ret", ret)):
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return f"{label} must be YYYY-MM-DD"
    # Codes only. These land in an argv list (never a shell), but a junk value
    # produces an opaque scraper error, so reject it here where we can say why.
    for label, value in (("origin", origin), ("dest", dest)):
        if not re.fullmatch(r"[A-Z]{3}(,[A-Z]{3})*", value):
            return f"{label} must be airport codes, e.g. NYC or JFK,EWR"
    return ""


def _add_fare_candidates(trip_id, results: list, direction: str, depart: str,
                          origin: str, dest: str, ret: str) -> list:
    added = []
    for r in results[:_FARE_KEEP]:
        out = r.get("outbound") or {}
        note = _fare_note(r, out, ret)
        # The tool reports clock times without a date. Stamping both ends with the
        # departure date keeps them parseable by triptime.parseStamp; an overnight
        # arrival will read a day early until the fare is actually booked and the
        # real times are entered.
        added.append(db.add_flight(trip_id, {
            "direction": direction,
            "airline": ", ".join(r.get("airlines") or []) or "",
            "from_airport": out.get("from") or origin,
            "to_airport": out.get("to") or dest,
            "departure_time": f"{depart} {out.get('depart', '')}".strip(),
            "arrival_time": f"{depart} {out.get('arrive', '')}".strip(),
            "cost": r.get("effective") if r.get("effective") is not None else r.get("price"),
            "status": "considering",
            "notes": note,
        }))
    return added


@_api.bp.route("/api/trips/<int:trip_id>/flights/search", methods=["POST"])
def api_search_fares(trip_id):
    """Run the vault's own fare search and write the top results in as candidates.

    Writes rows with status 'considering' — a search result is not a booking, and
    the whole point of the logistics comparison table is that candidates sit side
    by side until one is picked.
    """
    import subprocess

    body = request.get_json(force=True, silent=True) or {}
    origin = str(body.get("origin") or "").strip().upper()
    dest = str(body.get("dest") or "").strip().upper()
    depart = str(body.get("depart") or "").strip()
    ret = str(body.get("ret") or "").strip()
    err = _fare_search_error(origin, dest, depart, ret)
    if err:
        return jsonify({"error": err}), 400

    script = _code_root() / "bin" / "flight-search.py"
    if not script.exists():
        return jsonify({"error": "flight-search.py not found"}), 500
    cmd = [sys.executable, str(script), origin, dest, depart]
    if ret:
        cmd.append(ret)
    cmd.append("--json")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_FARE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return jsonify({"error": f"fare search timed out after {_FARE_TIMEOUT}s"}), 504
    if proc.returncode != 0:
        return jsonify({"error": (proc.stderr or "fare search failed").strip()[:400]}), 502
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return jsonify({"error": "fare search returned no usable data"}), 502

    results = payload.get("results") or []
    if not results:
        errs = "; ".join(payload.get("errors") or []) or "no fares returned"
        return jsonify({"error": errs, "added": 0}), 200

    # Google prices a search with a return date as one round-trip fare, and the
    # tool only ever reports the outbound leg's times. Calling that row "outbound"
    # reads as a one-way seat at the round-trip price, so it gets its own leg
    # value and the notes say which times you are looking at.
    direction = "roundtrip" if ret else "outbound"
    added = _add_fare_candidates(trip_id, results, direction, depart, origin, dest, ret)
    return jsonify({"added": len(added), "flights": added, "errors": payload.get("errors") or []})


def _code_root() -> Path:
    """The vault-code repo root — this file is <root>/dashboard/hub/trips/api_items.py."""
    return Path(__file__).resolve().parents[3]


@_api.bp.route("/api/trips/<int:trip_id>/transportation", methods=["POST"])
def api_add_transport(trip_id):
    return jsonify(db.add_transport(trip_id, request.get_json(force=True, silent=True) or {})), 201


@_api.bp.route("/api/trips/<int:trip_id>/transportation/<int:tid>", methods=["PATCH"])
def api_update_transport(trip_id, tid):
    row = db.update_transport(trip_id, tid, request.get_json(force=True, silent=True) or {})
    return jsonify(row) if row else (jsonify({"error": "not found"}), 404)


@_api.bp.route("/api/trips/<int:trip_id>/transportation/<int:tid>", methods=["DELETE"])
def api_delete_transport(trip_id, tid):
    return jsonify({"ok": db.delete_transport(trip_id, tid)})


@_api.bp.route("/api/trips/<int:trip_id>/expenses", methods=["POST"])
def api_add_expense(trip_id):
    return jsonify(db.add_expense(trip_id, request.get_json(force=True, silent=True) or {})), 201


@_api.bp.route("/api/trips/<int:trip_id>/expenses/<int:eid>", methods=["PATCH"])
def api_update_expense(trip_id, eid):
    row = db.update_expense(trip_id, eid, request.get_json(force=True, silent=True) or {})
    return jsonify(row) if row else (jsonify({"error": "not found"}), 404)


@_api.bp.route("/api/trips/<int:trip_id>/expenses/<int:eid>", methods=["DELETE"])
def api_delete_expense(trip_id, eid):
    return jsonify({"ok": db.delete_expense(trip_id, eid)})


# `item` is what the trips board calls the thing and `got` is what it calls a tick;
# `text` and `checked` are what a checklist calls them. Both spellings are accepted so
# an older client keeps working, and only the checklist's own field names go to the DB.
def _as_item(data: dict) -> dict:
    out = {k: data[k] for k in ("text", "section", "qty", "note", "sort_order")
           if k in data}
    if "item" in data:
        out["text"] = data["item"]
    if "got" in data:
        out["checked"] = 1 if data["got"] else 0
    if "checked" in data:
        out["checked"] = 1 if data["checked"] else 0
    return out


@_api.bp.route("/api/trips/<int:trip_id>/grocery", methods=["POST"])
def api_add_grocery(trip_id):
    """Add to the shared list, so every trip gets it. See db.grocery_list.

    The trips board speaks item/qty/note and a checklist speaks text/qty/note, so the
    one field that differs is renamed here rather than teaching either side the other's
    vocabulary. A tick is never written to the shared row: it is this trip's alone.
    """
    data = _as_item(request.get_json(force=True, silent=True) or {})
    data.pop("checked", None)
    cl = db.grocery_list()
    if cl is None:
        return jsonify({"error": "checklists unavailable"}), 503
    return jsonify(checklists_db.add_item(cl["id"], data)), 201


@_api.bp.route("/api/trips/<int:trip_id>/grocery/<int:gid>", methods=["PATCH"])
def api_update_grocery(trip_id, gid):
    """A tick lands on this trip; any other field edits the shared row."""
    data = _as_item(request.get_json(force=True, silent=True) or {})
    cl = db.grocery_list()
    if cl is None:
        return jsonify({"error": "checklists unavailable"}), 503
    row = next((i for i in cl["items"] if i["id"] == gid), None)
    if row is None:
        return jsonify({"error": "not found"}), 404
    checked = data.pop("checked", None)
    if data:
        row = checklists_db.update_item(cl["id"], gid, data)
    if checked is not None:
        db.set_packing_tick(trip_id, cl["id"], gid, bool(checked))
    # Row deleted between the read above and the update: the tick still lands
    # and the request 500s, exactly as before the split (zero behaviour change).
    assert row is not None
    row["checked"] = checked if checked is not None else int(
        (cl["id"], gid) in db.packing_ticks(trip_id))
    return jsonify(row)


@_api.bp.route("/api/trips/<int:trip_id>/grocery/<int:gid>", methods=["DELETE"])
def api_delete_grocery(trip_id, gid):
    cl = db.grocery_list()
    if cl is None:
        return jsonify({"error": "checklists unavailable"}), 503
    return jsonify({"ok": checklists_db.delete_item(cl["id"], gid)})


def _seed_departures(trip_id: int) -> None:
    """Give a newly scheduled day its "Leave home base" event.

    On the write path rather than as a backfill, because a backfill that never
    reaches the write path regenerates the gap the moment the next day is
    scheduled. Never overwrites an existing departure — see db.ensure_departures.
    Best-effort: a trip still schedules fine if this cannot work out a drive time.
    """
    try:
        db.ensure_departures(trip_id)
    except Exception:
        _api.logger.exception("ensure_departures failed")


@_api.bp.route("/api/trips/<int:trip_id>/activities", methods=["POST"])
def api_add_activity(trip_id):
    row = db.add_activity(trip_id, request.get_json(force=True, silent=True) or {})
    _seed_departures(trip_id)
    return jsonify(row), 201


@_api.bp.route("/api/trips/<int:trip_id>/activities/<int:aid>", methods=["PATCH"])
def api_update_activity(trip_id, aid):
    data = request.get_json(force=True, silent=True) or {}
    row = db.update_activity(trip_id, aid, data)
    if not row:
        return jsonify({"error": "not found"}), 404
    _seed_departures(trip_id)
    if _api._cal_ready():
        trip = db.get_trip(trip_id)
        if trip:
            trip["tz"] = db.trip_tz(trip_id)
            is_scheduled = row.get("status") == "scheduled" and row.get("scheduled_date")
            cal_event_id = row.get("cal_event_id")
            if is_scheduled:
                try:
                    new_id = _api.gcal.push_activity(row, trip)
                    if new_id and new_id != cal_event_id:
                        db.set_activity_cal_event_id(aid, new_id)
                        row["cal_event_id"] = new_id
                except Exception:
                    _api.logger.exception("push_activity failed")
            elif cal_event_id and row.get("status") not in ("scheduled",):
                try:
                    _api.gcal.delete_event(cal_event_id)
                    db.set_activity_cal_event_id(aid, None)
                    row["cal_event_id"] = None
                except Exception:
                    _api.logger.exception("delete_event (unschedule) failed")
    return jsonify(row)


@_api.bp.route("/api/trips/<int:trip_id>/activities/<int:aid>", methods=["DELETE"])
def api_delete_activity(trip_id, aid):
    activity = db.get_activity(aid, trip_id)
    if activity and activity.get("cal_event_id") and _api._cal_ready():
        try:
            _api.gcal.delete_event(activity["cal_event_id"])
        except Exception:
            _api.logger.exception("delete_event (activity delete) failed")
    return jsonify({"ok": db.delete_activity(trip_id, aid)})


@_api.bp.route("/api/trips/<int:trip_id>/activities/<int:aid>/opinions", methods=["POST"])
def api_upsert_opinion(trip_id: int, aid: int):
    data = request.get_json(force=True, silent=True) or {}
    member_id = data.get("member_id")
    if not member_id:
        return jsonify({"error": "member_id required"}), 400
    db.upsert_opinion(aid, int(member_id), data.get("rating"))
    return jsonify({"ok": True})
