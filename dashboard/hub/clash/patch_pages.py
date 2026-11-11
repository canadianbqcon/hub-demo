"""Patch page: the page shell, one read view and a manual refresh (routes join api.bp)."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from flask import jsonify, request

from vault_path import vault_root

from . import db, patch
from .api import _err, _shell, bp
from .war_pages import _age

LOCK_PATH = Path(vault_root()) / ".pending" / "clash-patch.lock"  # the scheduler job takes this same file
POSTS, BLOG, LEAKS = 50, 50, 90


def _get():
    return patch.http_get


def _client():
    return patch.make_client()


@bp.route("/patch")
def patch_page():
    return _shell("patch")


@bp.route("/api/patch")
def api_patch():
    """Newest first. `before` pages the three lists, strict less-than, each on its own column:
    posts and blog on posted_on (YYYY-MM-DD), leaks on posted_at (ISO timestamp). One value serves
    both: a bare date excludes that whole day of leaks, a full timestamp cuts leaks exactly and
    blog by its date part. posts = balance/update posts that are classified, with entries."""
    before = request.args.get("before") or None
    with db.conn() as c:
        def rows(sql, col, n):
            where, args = (f"AND {col} < ?", [before]) if before else ("", [])
            return c.execute(sql.format(where=where), (*args, n)).fetchall()

        posts = rows("SELECT slug FROM blog_post WHERE kind IN ('balance','update') AND classify_state='done' "
                     "{where} ORDER BY posted_on DESC, slug LIMIT ?", "posted_on", POSTS)
        blog = rows("SELECT slug, title, url, posted_on AS date, kind, classify_state FROM blog_post WHERE 1 "
                    "{where} ORDER BY posted_on DESC, slug LIMIT ?", "posted_on", BLOG)
        leaks = rows("SELECT id, title, credit, author, score, comments, posted_at, url, image_url FROM leak_post "
                     "WHERE 1 {where} ORDER BY posted_at DESC, id LIMIT ?", "posted_at", LEAKS)
        fetch = {}
        for src in ("blog", "leaks", "classify"):
            r = c.execute("SELECT ok_at, last_error FROM patch_fetch WHERE source=?", (src,)).fetchone()
            fetch[src] = {"ok_at": r and r["ok_at"], "last_error": r and r["last_error"],
                          "age_secs": _age(r["ok_at"]) if r and r["ok_at"] else None}
        n = lambda s: c.execute("SELECT count(*) FROM blog_post WHERE classify_state=?", (s,)).fetchone()[0]
        bf = c.execute("SELECT backfill_page FROM patch_fetch WHERE source='blog'").fetchone()
        return jsonify({"posts": [patch.post_view(c, r["slug"]) for r in posts], "blog": [dict(r) for r in blog],
                        "leaks": [dict(r) for r in leaks], "fetch": fetch, "unsorted": n("pending"),
                        "failed": n("failed"), "blog_total": c.execute("SELECT count(*) FROM blog_post").fetchone()[0],
                        "backfill_done": bf is not None and bf[0] is None})


@bp.route("/api/patch/refresh", methods=["POST"])
def api_patch_refresh():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return _err("a refresh is already running", 409)
        # ponytail: runs inside the request (up to ~1 minute with 5 classify calls); a background thread if it ever times out
        with db.conn() as c:
            return jsonify(patch.run(c, _get(), _client()))
    finally:
        os.close(fd)
