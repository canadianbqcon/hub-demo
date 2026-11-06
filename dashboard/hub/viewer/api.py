"""Viewer Hub blueprint: routes under /viewer.

The page, the cached feed, hardened file serving and the upload. Storage and
retention live in viewer/store.py.
"""

from __future__ import annotations

import mimetypes
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, cast

from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

# hub/ on sys.path so marks and viewer import when this file loads standalone
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marks.api import _same_site  # noqa: E402
from viewer import store, terminals  # noqa: E402

MAX_BYTES = 2 << 30  # per request
MAX_FILES = 50  # per drop
MIN_FREE = 2 << 30  # refuse an upload under this much free space

# Shown in the browser; everything else (HTML, SVG, scripts, RAW) downloads.
INLINE = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/avif",
    "video/mp4", "video/webm", "video/quicktime", "application/pdf",
}

bp = Blueprint("viewer", __name__, static_folder="frontend/static", url_prefix="/viewer")

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")


@bp.route("/")
def index():
    return send_from_directory(_FRONTEND_DIR, "viewer.html")


@bp.get("/api/feed")
def api_feed():
    # the app-wide after_request hook ETags this, so an unchanged feed is a 304
    return jsonify({"items": store.feed()})


@bp.get("/file/<item_id>/<name>")
def file(item_id, name):
    p = store.resolve(item_id, name)
    if p is None:
        return jsonify({"error": "not found"}), 404
    mime = mimetypes.guess_type(p.name)[0]
    r = send_from_directory(p.parent, p.name, as_attachment=mime not in INLINE)
    r.headers["X-Content-Type-Options"] = "nosniff"
    if mime != "application/pdf":  # Chrome refuses to open its PDF viewer in a sandboxed document
        r.headers["Content-Security-Policy"] = "sandbox"
    return r


@bp.get("/api/terminals")
def api_terminals():
    try:
        return jsonify({"terminals": terminals.terminals()})
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        return jsonify({"error": f"could not list terminals: {type(e).__name__}"}), 502


@bp.post("/api/send")
def api_send():
    """Type a line into a Claude terminal pointing it at one item's files (or page)."""
    if not _same_site():
        return jsonify({"error": "cross-site send refused"}), 403
    body = request.get_json(silent=True) or {}
    it = next((i for i in store.feed() if i["id"] == body.get("item")), None)
    if it is None:
        return jsonify({"error": "no such item"}), 404
    what = it.get("url") if it["kind"] == "web" else " ".join(f'"{p}"' for p in store.paths(it))
    if not what:
        return jsonify({"error": "item has nothing to send"}), 400
    line = f"Look at what I sent you from the Hub Viewer ({it['title']}): {what}"
    try:
        ok = terminals.send(str(body.get("pane") or ""), line)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        return jsonify({"error": f"could not reach the terminal: {type(e).__name__}"}), 502
    if not ok:
        return jsonify({"error": "that terminal is gone"}), 409
    return jsonify({"ok": True})


@bp.post("/api/upload")
def upload():
    if not _same_site():
        return jsonify({"error": "cross-site upload refused"}), 403
    store.ROOT.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(store.ROOT).free < MIN_FREE:
        return jsonify({"error": "not enough free disk space"}), 507
    if (request.content_length or 0) > MAX_BYTES:
        return jsonify({"error": "upload too large"}), 413
    request.max_content_length = MAX_BYTES  # also bounds a chunked body
    try:
        files = [f for f in request.files.getlist("files") if f.filename]
    except RequestEntityTooLarge:
        return jsonify({"error": "upload too large"}), 413
    if not files:
        return jsonify({"error": "no files"}), 400
    if len(files) > MAX_FILES:
        return jsonify({"error": f"at most {MAX_FILES} files per drop"}), 413
    first = os.path.basename((files[0].filename or "").replace("\\", "/"))
    title = first if len(files) == 1 else f"{first} +{len(files) - 1} more"
    item_id, staging = store.stage(title)
    try:
        for f in files:
            store.add_file(staging, cast(BinaryIO, f.stream), f.filename or "")
        item = store.commit(item_id, staging, kind="upload", title=title, source="Upload")
    except Exception:
        store.discard(staging)
        raise
    return jsonify({"item": item})
