"""Artifacts Hub blueprint — routes under /artifacts.

Serves a browsable catalog of Sam's published claude.ai Artifacts, read
from data/artifacts.json (hand-maintained). Mirrors the capabilities module:
a static page plus one JSON api route. No database, no init() wiring — the
vault path is resolved directly via vault_root() (purchases pattern).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from flask import Blueprint, Response, send_from_directory

# dashboard/ on sys.path → vault_path (the Hub already inserts it, but keep the
# blueprint importable standalone too).
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

bp = Blueprint(
    "artifacts",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/artifacts",
)

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
_ARTIFACTS_JSON = vault_root() / "data" / "artifacts.json"


@bp.route("/")
def index():
    return send_from_directory(_FRONTEND_DIR, "artifacts.html")


@bp.route("/api/data", methods=["GET"])
def api_data():
    # Read fresh each request so a hand-edit to artifacts.json shows without a
    # restart. Missing/broken file yields an empty list rather than a 500.
    try:
        payload = json.loads(_ARTIFACTS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {"artifacts": []}
    return Response(json.dumps(payload), mimetype="application/json")
