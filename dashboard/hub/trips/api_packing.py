"""Packing-list routes.

Split from trips/api.py (Task 3 of the 2026-09-24 trips-split plan; Task 4
moved `packing_rank` and the `_PACKING_*` constants in here from the facade,
to keep api.py under 500 lines — tests that did `from trips.api import
packing_rank` still work, since this file's names are re-exported from
`trips.api` same as everything else it owns). See
dashboard/hub/tests/test_trips_facades.py.
"""

from __future__ import annotations

from flask import jsonify, request

from checklists import db as checklists_db

from . import api as _api
from . import db

# Sam's own lists, read straight out of checklists.db: everything /checklists
# files under "packing", plus the activity-specific lists (Rave, Beach, Snowboarding,
# Camera Gear) that sit beside them there. The CONTENTS are /checklists' and are
# never copied; the TICKS are the trip's own and live in trips.packing_ticks, so
# packing for Denver leaves the Toiletries list on /checklists untouched and the
# next trip starts from nothing. Withheld from the mirror (public_app._WITHHELD_PREFIXES):
# a guest's board has no business showing somebody else's toiletries, and the
# read-only gate would refuse the writes anyway.
_PACKING_CATEGORIES = ("packing", "activity")

# Reading order on the packing tab. The seed's ids no longer give it: Camera Gear
# is filed "activity" but packs on every trip, and it belongs above the first aid
# kit rather than after it. Anything not named here falls in after, by id.
# ponytail: matched on name, so a rename on /checklists drops that list to the
# tail — fine until a list is actually renamed, then move the order into the db.
_PACKING_ORDER = (
    "Travel", "Clothes", "Toiletries", "Tech Gear",
    "Miscellaneous", "Camera Accessories", "First Aid Kit",
)

# Not every trip is a beach trip. These three ride along only when the board asks
# for them, so they come back flagged and the tab decides whether to draw them.
_PACKING_OPTIONAL = ("Beach", "Snowboarding", "Rave")


def packing_rank(cl):
    """Sort key: the optional three last, then the declared order, then seed order."""
    try:
        named = _PACKING_ORDER.index(cl["name"])
    except ValueError:
        named = len(_PACKING_ORDER)
    return (cl["name"] in _PACKING_OPTIONAL, named, cl["id"])


@_api.bp.route("/api/packing/<int:trip_id>")
def api_packing(trip_id):
    """The lists as /checklists holds them, with each item's checked flag replaced
    by whether THIS trip has packed it."""
    if checklists_db._db_path is None:
        return jsonify({"error": "checklists unavailable"}), 503
    ticks = db.packing_ticks(trip_id)
    heads = [cl for cl in checklists_db.list_checklists() if cl["category"] in _PACKING_CATEGORIES]
    heads.sort(key=packing_rank)
    lists = []
    for cl in heads:
        full = checklists_db.get_checklist(cl["id"])
        if not full:
            continue
        for item in full.get("items") or []:
            item["checked"] = 1 if (cl["id"], item["id"]) in ticks else 0
        full["optional"] = full["name"] in _PACKING_OPTIONAL
        lists.append(full)
    return jsonify(lists)


@_api.bp.route("/api/packing/<int:trip_id>/<int:cid>/items/<int:item_id>", methods=["PATCH"])
def api_packing_tick(trip_id, cid, item_id):
    data = request.get_json(force=True, silent=True) or {}
    checked = 1 if data.get("checked") else 0
    db.set_packing_tick(trip_id, cid, item_id, bool(checked))
    return jsonify({"id": item_id, "checklist_id": cid, "trip_id": trip_id, "checked": checked})


@_api.bp.route("/api/packing/<int:trip_id>/<int:cid>/reset", methods=["POST"])
def api_packing_reset(trip_id, cid):
    return jsonify({"cleared": db.clear_packing_ticks(trip_id, cid)})
