"""Routes for the Hub bell: GET /notify/api/list, POST /notify/api/read and /notify/api/delete,
GET /notify/go/<id>.

Behind the Hub's sign-in gate like every route; nothing here is on a public list.
The app-wide _conditional_json hook adds the ETag to the list.
"""

from __future__ import annotations

import sqlite3

from flask import Blueprint, abort, jsonify, redirect, request

from . import db

bp = Blueprint("notify", __name__, url_prefix="/notify")


def _unavailable():
    return jsonify({"error": "unavailable"}), 503


@bp.route("/api/list")
def api_list():
    try:
        conn = db.connect()
        try:
            return jsonify(db.list_items(conn))
        finally:
            conn.close()
    except sqlite3.Error:
        return _unavailable()


def _ids():
    """The {"ids": [n, ...]} body both POSTs take, or None when it is anything else."""
    body = request.get_json(silent=True)
    ids = body.get("ids") if isinstance(body, dict) and set(body) == {"ids"} else None
    ok = isinstance(ids, list) and ids and all(type(i) is int and 0 < i < 2**63 for i in ids)
    return ids if ok else None


def _change(fn):
    ids = _ids()
    if ids is None:
        return jsonify({"error": "bad request"}), 400
    try:
        conn = db.connect()
        try:
            fn(conn, ids)
            return jsonify({"ok": True, **db.list_items(conn)})  # the bell shows this list as is
        finally:
            conn.close()
    except sqlite3.Error:
        return _unavailable()


@bp.route("/api/read", methods=["POST"])
def api_read():
    return _change(db.mark_read)


@bp.route("/api/delete", methods=["POST"])
def api_delete():
    return _change(db.delete)


@bp.route("/go/<int:nid>")
def go(nid):
    """An unread row's link: mark it read, then redirect to its url. Marking on the
    server before the redirect covers every way of opening it (click, middle-click,
    new tab) and means the next page's bell never sees it unread."""
    if nid >= 2**63:
        abort(404)
    url = None
    try:
        conn = db.connect()
        try:
            r = conn.execute("SELECT url FROM notification WHERE id=?", (nid,)).fetchone()
            url = db._check_url(r["url"]) if r else None  # stored urls passed post(); checked again anyway
            db.mark_read(conn, [nid])  # after the read, so a locked store still sends him to the page
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        pass  # fail open: the url (if read) or Home
    return redirect(url or "/")
