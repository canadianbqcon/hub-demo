from __future__ import annotations

import json
import os
import time

from flask import Blueprint, Response, send_from_directory

from . import scan

bp = Blueprint(
    "capabilities",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/capabilities",
)

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
_VAULT: str | None = None


def init(vault: str) -> None:
    """Stash the vault path for api_data() to scan from. Call once at app startup."""
    global _VAULT
    _VAULT = vault


# ── Page ──────────────────────────────────────────────────────────────────────


@bp.route("/")
def index():
    return send_from_directory(_FRONTEND_DIR, "capabilities.html")


# ── API ───────────────────────────────────────────────────────────────────────


# scan.collect() walks the vault filesystem end to end — 700-800 ms, paid by the
# reader on every load of a page whose answer changes when a skill or hook file is
# added, i.e. a few times a week. A minute of staleness is invisible here.
# ponytail: one module-level tuple, no invalidation hook — the TTL is the whole design.
_TTL = 60
_cache: tuple[float, str] | None = None


def _payload() -> str:
    global _cache
    if not _cache or time.monotonic() - _cache[0] >= _TTL:
        assert _VAULT is not None, "capabilities.init() was never called at app startup"
        # jsonify() sorts keys alphabetically by default, which would silently
        # undo the usefulness-ordered CATEGORIES list in scan.py.
        _cache = (time.monotonic(), json.dumps(scan.collect(_VAULT)))
    return _cache[1]


@bp.route("/api/data", methods=["GET"])
def api_data():
    # init() is called at app startup; if the blueprint is registered without it,
    # scan.collect(None) would fail deep inside the walk with an opaque error.
    # Fail here instead, where the cause is obvious.
    if _VAULT is None:
        return Response(
            json.dumps({"error": "capabilities blueprint not initialised — call init(vault)"}),
            status=503, mimetype="application/json",
        )
    return Response(_payload(), mimetype="application/json")
