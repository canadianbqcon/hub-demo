from __future__ import annotations

import json
import os

from flask import Blueprint, Response, jsonify, send_from_directory

from . import db

bp = Blueprint(
    "vault_map",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/vault-map",
)

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")


# ── Page ──────────────────────────────────────────────────────────────────────


@bp.route("/")
def index():
    # The interactive Miller-columns map: drill-right columns with lit ancestry,
    # click-only select, a terminal-leaf info panel, and the 10-bucket function
    # palette. Served as a static file (no Jinja) so the inline ${…} template
    # literals and CSS braces pass through untouched. It reads the live cache
    # from /vault-map/api/tree; populate that cache with POST /vault-map/api/refresh.
    return send_from_directory(_FRONTEND_DIR, "vault_map.html")


# ── API ───────────────────────────────────────────────────────────────────────


# The tree is 4.4 MB of JSON read out of sqlite and serialised — 300+ ms per load,
# for a cache that only changes when api_refresh() rebuilds it. So build it once and
# hand back the same string until a refresh explicitly drops it. The app-wide ETag
# hook turns the unchanged body into a 304, so a repeat visit transfers nothing.
_tree_json: str | None = None
# Never read by the page, and on every one of ~44k rows: generated_at alone was
# 0.9 MB. Null fields go too (~197k of them); the page reads with `== null`, so a
# missing key and a null read the same. 18.6 MB -> 13.6 MB the browser must parse.
_UNSENT = {"generated_at", "wiki_slug"}


def _wire(row: dict) -> dict:
    return {k: v for k, v in row.items() if v is not None and k not in _UNSENT}


@bp.route("/api/tree", methods=["GET"])
def api_tree():
    global _tree_json
    if _tree_json is None:
        _tree_json = json.dumps(
            {"status": "ok", "count": db.node_count(), "nodes": [_wire(r) for r in db.get_tree()]},
            separators=(",", ":"),
        )
    return Response(_tree_json, mimetype="application/json")


def rebuild() -> int:
    """Rewalk both repos into the cache and drop the served JSON. Also run daily
    by the scheduler's vault-map-refresh job, since a walk takes ~3 minutes."""
    global _tree_json
    count = db.refresh()
    _tree_json = None          # the only thing that can change the tree
    return count


@bp.route("/api/refresh", methods=["POST"])
def api_refresh():
    return jsonify({"status": "ok", "count": rebuild()})
