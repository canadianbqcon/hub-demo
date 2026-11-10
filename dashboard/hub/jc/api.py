from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

# The Juniper & Co page: a straight copy of the "Juniper & Co Bar Back" artifact
# (open, close, batch prep, cocktails, map, stock), swapped in for the old
# three-tab umbrella 2026-11-09. Served as a static file, not a template, so the
# artifact's own markup is never run through Jinja.
# ponytail: no window.claude here, so the page runs in its built-in local mode
# (state saved in this browser only). Add a Hub-backed db shim if two devices
# need to share one board.
bp = Blueprint(
    "jc",
    __name__,
    static_folder="frontend/static",
    url_prefix="/jc",
)

_FRONTEND = Path(__file__).parent / "frontend"


@bp.route("/")
def index():
    return send_from_directory(_FRONTEND, "barback.html")


@bp.route("/api/shifts")
def shifts():
    """J&Co scheduled shifts between ?from= and ?to= (YYYY-MM-DD), as {date: [start, end]}.
    Read from earnings_scheduled_shifts, which the calendar sync fills; drives the week bar."""
    from finances.shift_calendar import _conn
    lo, hi = request.args.get("from", ""), request.args.get("to", "")
    with _conn() as conn:
        rows = conn.execute(
            "SELECT shift_date, start_at, end_at FROM earnings_scheduled_shifts "
            "WHERE source = 'juniper-and-co' AND shift_date BETWEEN ? AND ? AND start_at IS NOT NULL",
            (lo, hi)).fetchall()
    return jsonify({r[0]: [r[1], r[2]] for r in rows})
