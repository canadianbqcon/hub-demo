from __future__ import annotations

import logging
from datetime import datetime

from flask import Blueprint, jsonify, redirect, request

from . import db

logger = logging.getLogger(__name__)

# Barback shift companion for Juniper & Co, served by the Hub app (port 5002).
# The DATA API still lives here at /barback/api/barback/* and is unchanged; the
# page itself moved into the juniper & co umbrella (/jc/#barback) when the
# three J&Co surfaces merged onto one tabbed page. Tailnet only.

bp = Blueprint(
    "barback",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/barback",
)


def _ok(data):
    return jsonify({"status": "ok", "data": data})


def _err(message: str, code: int = 400):
    return jsonify({"status": "error", "message": message}), code


@bp.route("/")
def index():
    """The page is a tab of /jc/ now. Kept as a 308 so bookmarks, the phone's
    home-screen shortcut and any old link still land in the right place —
    same treatment /jobs/ got when it became /apply/."""
    return redirect("/jc/#barback", code=308)


@bp.route("/api/barback/run", methods=["POST"])
def api_run_start():
    """Start or resume today's run for a template key (body: {key})."""
    payload = request.get_json(silent=True) or {}
    key = (payload.get("key") or "").strip()
    if not key:
        return _err("key required", 400)
    try:
        return _ok(db.start_run(key, datetime.now()))
    except ValueError as e:
        return _err(str(e), 400)


@bp.route("/api/barback/run/<int:run_id>")
def api_run_get(run_id: int):
    run = db.get_run(run_id)
    if run is None:
        return _err(f"run {run_id} not found", 404)
    return _ok(run)


@bp.route("/api/barback/run/item/<int:item_id>", methods=["PUT"])
def api_run_item(item_id: int):
    """Set an item's state (duty: done/open; stock: good/low/out/open)."""
    payload = request.get_json(silent=True) or {}
    state = (payload.get("state") or "").strip()
    if not state:
        return _err("state required", 400)
    try:
        item = db.set_item_state(item_id, state)
    except ValueError as e:
        return _err(str(e), 400)
    if item is None:
        return _err(f"item {item_id} not found", 404)
    return _ok(item)


@bp.route("/api/barback/run/<int:run_id>/clear", methods=["POST"])
def api_run_clear(run_id: int):
    """Zero every count in a fill run — the 'clear all' on the low boy."""
    if db.get_run(run_id) is None:
        return _err(f"run {run_id} not found", 404)
    try:
        cleared = db.clear_fill_run(run_id)
    except ValueError as e:
        return _err(str(e), 400)
    return _ok({"cleared": cleared})


@bp.route("/api/barback/run/<int:run_id>/sweep")
def api_sweep(run_id: int):
    """Low boy grab list for a fill run, grouped by walkable storage area."""
    if db.get_run(run_id) is None:
        return _err(f"run {run_id} not found", 404)
    return _ok(db.grab_sweep(run_id))


@bp.route("/api/barback/run/<int:run_id>/lowout")
def api_lowout(run_id: int):
    if db.get_run(run_id) is None:
        return _err(f"run {run_id} not found", 404)
    return _ok(db.lowout_summary(run_id))


