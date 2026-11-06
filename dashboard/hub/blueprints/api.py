"""The /blueprints page: the Hub's shared UI vocabulary, rendered from its own CSS.

Read-only. Every response is generated from static/css/base.css + chrome.css at
request time, so the page cannot disagree with what ships. No cache: the shared
layer is 548 lines and the whole resolve is a few milliseconds, so a TTL would buy
nothing and could show a stale component to someone editing one.
"""

from __future__ import annotations

import json
import os

from flask import Blueprint, Response, redirect, request, send_from_directory

from . import extract, resolve

bp = Blueprint(
    "blueprints",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/blueprints",
)

# /elements was this page's address until 2026-09-09. A 301 rather than a rename-
# and-forget: the address is in Sam's bookmarks and in three governance files
# that predate the rename.
legacy_bp = Blueprint("elements_legacy", __name__, url_prefix="/elements")

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")


@bp.route("/")
def index():
    return send_from_directory(_FRONTEND_DIR, "blueprints.html")


@legacy_bp.route("/", defaults={"rest": ""})
@legacy_bp.route("/<path:rest>")
def moved(rest):
    qs = request.query_string.decode()
    return redirect(f"/blueprints/{rest}" + (f"?{qs}" if qs else ""), code=301)


@bp.route("/api/blueprints.json", methods=["GET"])
def api_blueprints():
    # ?resolved=1 inlines the live CSS + derived tokens. The bare form is the
    # authored file, for a caller that only wants the rules and markup.
    if request.args.get("resolved") in ("1", "true", "yes"):
        payload = resolve.resolve_all()
    else:
        payload = resolve.load()
    return Response(json.dumps(payload), mimetype="application/json")


@bp.route("/api/budget.json", methods=["GET"])
def api_budget():
    """Page CSS line counts, measured at request time like everything else here.
    A readout, not a cap: the line cap was retired 2026-10-15 for the markup check."""
    lines = extract.stylesheet_lines()
    return Response(
        json.dumps({
            "total": sum(lines.values()),
            "files": [
                {"path": p, "lines": n}
                for p, n in sorted(lines.items(), key=lambda kv: -kv[1])
            ],
        }),
        mimetype="application/json",
    )
