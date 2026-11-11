"""Plan and layouts pages for /clash. Routes attach to api.bp; api.py imports this module at its bottom."""

from __future__ import annotations

import json
import re
import uuid

from flask import abort, jsonify, request, send_from_directory

from . import db, gamedata, plan
from .api import _acct, _err, _shell, _tag, bp

MAX_IMG = 10 * 1024 * 1024
NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp)$")


@bp.route("/plan")
def plan_page():
    return _shell("plan")


@bp.route("/layouts")
def layouts_page():
    return _shell("layouts")


def _have(raw):
    """have= is a JSON object {"Gold": 100}; anything else counts as nothing."""
    try:
        h = json.loads(raw or "{}")
    except ValueError:
        return {}
    return {str(k): int(v) for k, v in h.items() if isinstance(v, (int, float))} if isinstance(h, dict) else {}


@bp.route("/api/plan")
def plan_api():
    with db.conn() as c:
        db.apply_due(c, db.now())
        acct = _tag(c, request.args.get("tag"))
        if not acct:
            return _err("Unknown account", 404)
        village = []
        for r in c.execute("SELECT data_id, level, cnt FROM structure WHERE tag=?", (acct["tag"],)):
            try:
                gamedata.entity(r["data_id"])
            except KeyError:
                continue
            village.append(dict(r))
        ups = [{**dict(r), "finishes_at": db.parse(r["finishes_at"])}
               for r in c.execute("SELECT * FROM upgrade WHERE tag=?", (acct["tag"],))]
        ups = [u for u in ups if u["facility"] == "builder"]
        now = db.parse(db.now())
        try:
            q = plan.builder_queue(village, ups, acct["builders"], now)
            th = plan._town_hall(gamedata, village)
        except ValueError as e:  # no Town Hall in the village yet
            return _err(str(e), 409)
        res = plan.resources(q, _have(request.args.get("have")))
        lanes = [[{"data_id": i["data_id"], "name": gamedata.entity(i["data_id"])["name"],
                   "icon": gamedata.icon(i["data_id"]), "level": i["level"],
                   "start": i["start"].strftime(db.FMT), "end": i["end"].strftime(db.FMT)} for i in lane] for lane in q["lanes"]]
        return jsonify({
            "tag": acct["tag"], "th": th, "builders": acct["builders"],
            "estimate": "Estimate: no boosts, no Gold Pass discount, builders always busy.",
            "lanes": lanes, "done_at": q["done_at"].strftime(db.FMT),
            "walls": plan.walls(village, th), "resources": res})


# ---- layouts ----

def _dir():
    d = db._db_path.parent / "clash" / "layouts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _kind(head: bytes):
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _save(f):
    """Validated upload -> server-made file name, or (None, error)."""
    data = f.stream.read(MAX_IMG + 1)
    if len(data) > MAX_IMG:
        return None, "Image is over 10 MB"
    ext = _kind(data[:12])
    if not ext:
        return None, "Image must be PNG, JPEG or WebP"
    name = f"{uuid.uuid4().hex}.{ext}"
    (_dir() / name).write_bytes(data)
    return name, None


def _unlink(name):
    if name and NAME_RE.match(name):
        (_dir() / name).unlink(missing_ok=True)


def _form():
    return request.form if request.form else (request.get_json(silent=True) or {})


def _fields(b):
    link = str(b.get("link") or "").strip()
    if link and not re.match(r"^https?://", link, re.I):
        return None, "Link must start with http:// or https://"
    try:
        th = int(b.get("th_level"))
    except (TypeError, ValueError):
        return None, "th_level must be a number"
    if not 1 <= th <= 30:
        return None, "th_level must be 1 to 30"
    return {"th_level": th, "link": link, "notes": str(b.get("notes") or "").strip()}, None


@bp.route("/api/layouts", methods=["GET"])
def layouts_list():
    with db.conn() as c:
        acct = _tag(c, request.args.get("tag"))
        if not acct:
            return jsonify({"tag": None, "layouts": []})
        rows = c.execute("SELECT * FROM layout WHERE tag=? ORDER BY th_level DESC, id DESC", (acct["tag"],))
        return jsonify({"tag": acct["tag"], "layouts": [dict(r) for r in rows]})


@bp.route("/api/layouts", methods=["POST"])
def layouts_add():
    b = _form()
    f, e = _fields(b)
    if e:
        return _err(e, 400)
    name = ""
    up = request.files.get("image")
    if up and up.filename:
        name, e = _save(up)
        if e:
            return _err(e, 400)
    with db.conn() as c:
        acct = _acct(c, b.get("tag"))
        if not acct:
            _unlink(name)
            return _err("Unknown account", 404)
        cur = c.execute("INSERT INTO layout (tag, th_level, link, image_file, notes) VALUES (?,?,?,?,?)",
                        (acct["tag"], f["th_level"], f["link"], name, f["notes"]))
        return jsonify({"id": cur.lastrowid, "image_file": name}), 201


@bp.route("/api/layouts", methods=["PUT"])
def layouts_edit():
    b = _form()
    f, e = _fields(b)
    if e:
        return _err(e, 400)
    with db.conn() as c:
        row = c.execute("SELECT * FROM layout WHERE id=?", (b.get("id"),)).fetchone()
        if not row:
            return _err("Unknown layout", 404)
        name = row["image_file"]
        up = request.files.get("image")
        if up and up.filename:
            new, e = _save(up)
            if e:
                return _err(e, 400)
            name = new
        c.execute("UPDATE layout SET th_level=?, link=?, notes=?, image_file=? WHERE id=?",
                  (f["th_level"], f["link"], f["notes"], name, row["id"]))
    if name != row["image_file"]:
        _unlink(row["image_file"])
    return jsonify({"id": row["id"], "image_file": name})


@bp.route("/api/layouts", methods=["DELETE"])
def layouts_delete():
    b = request.get_json(silent=True) or {}
    lid = request.args.get("id") or b.get("id")
    with db.conn() as c:
        row = c.execute("SELECT image_file FROM layout WHERE id=?", (lid,)).fetchone()
        if not row:
            return _err("Unknown layout", 404)
        c.execute("DELETE FROM layout WHERE id=?", (lid,))
    _unlink(row["image_file"])
    return jsonify({"deleted": True})


@bp.route("/layouts/img/<name>")
def layout_img(name):
    if not NAME_RE.match(name):
        abort(404)
    return send_from_directory(_dir(), name)
